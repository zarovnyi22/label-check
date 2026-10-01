"""eval/run.py with FakeVision on 3 synthetic dev cases and the *_test database: cache only vs
live, pauses, a model error that does not stop the run, the test-split groups."""

import dataclasses
import json
import shutil

import pytest

from app.rules.engine import run_rules
from app.schemas import LabelExtraction, ProductSpec
from app.vision.base import VisionError
from app.vision.fake import FakeVision
from eval.run import NotCachedError, Unit, collect_units, run_units

PAUSE = 5.0


def truth_of(unit: Unit) -> dict:
    return json.loads((unit.folder / "truth.json").read_text(encoding="utf-8"))["extraction"]


@pytest.fixture
def units():
    picked = collect_units("dev")[:3]
    assert len(picked) == 3 and all(u.photos() for u in picked)
    return picked


@pytest.fixture(autouse=True)
def cache_root(tmp_path, monkeypatch):
    """Never write the committed eval/cache from tests."""
    root = tmp_path / "cache"
    monkeypatch.setattr("eval.run.CACHE", root)
    return root


async def run(pool, vision, units, *, live, pauses=None):
    async def sleep(seconds):
        (pauses if pauses is not None else []).append(seconds)

    return await run_units(
        pool,
        vision,
        units,
        live=live,
        pause_seconds=PAUSE,
        deadline_seconds=30,
        cache_root=cache_root_of(),
        sleep=sleep,
        log=lambda _: None,
    )


async def test_without_live_and_cache_it_lists_the_cases_and_calls_nothing(db_pool, units):
    vision = FakeVision()
    with pytest.raises(NotCachedError) as err:
        await run(db_pool, vision, units, live=False)
    assert all(u.case in str(err.value) for u in units)
    assert vision.calls == []


async def test_live_then_from_the_cache(db_pool, units):
    vision = FakeVision([truth_of(u) for u in units])
    pauses: list[float] = []
    results = await run(db_pool, vision, units, live=True, pauses=pauses)
    assert len(vision.calls) == 3 and pauses == [PAUSE, PAUSE]  # between calls, not before
    assert [r["status"] for r in results] == ["done"] * 3
    assert {r["source"] for r in results} == {"live"}
    # the model answered the truth, so the runner gives exactly the rules on the truth
    for unit, r in zip(units, results, strict=True):
        spec = unit.folder / unit.spec_file if unit.spec_file else None
        spec = ProductSpec.model_validate_json(spec.read_text()) if spec else None
        findings, verdict = run_rules(LabelExtraction.model_validate(truth_of(unit)), spec)
        assert r["verdict"] == verdict
        assert r["findings"] == [
            {"rule_id": f.rule_id, "target": f.target, "status": f.status} for f in findings
        ]
        assert r["in_trust_number"] and r["group"] == "synthetic"

    again = await run(db_pool, vision, units, live=False)  # no answers left: must not call
    assert {r["source"] for r in again} == {"file"} and len(vision.calls) == 3
    assert [r["verdict"] for r in again] == [r["verdict"] for r in results]


async def test_a_model_error_does_not_stop_the_run_and_only_it_is_retried(db_pool, units):
    error = VisionError("down", code="vision_unavailable", status_code=503)
    vision = FakeVision([error, truth_of(units[1]), truth_of(units[2])])
    results = await run(db_pool, vision, units, live=True)
    assert [r["status"] for r in results] == ["error", "done", "done"]
    assert results[0]["error"]["code"] == "vision_unavailable" and "verdict" not in results[0]

    with pytest.raises(NotCachedError) as err:  # the error was not cached
        await run(db_pool, FakeVision(), units, live=False)
    assert units[0].case in str(err.value) and units[1].case not in str(err.value)

    vision = FakeVision([truth_of(units[0])])
    results = await run(db_pool, vision, units, live=True)
    assert len(vision.calls) == 1 and [r["status"] for r in results] == ["done"] * 3


async def test_a_case_without_photos_is_listed(db_pool, units, tmp_path):
    empty = Unit("x", "x", "test", "real", tmp_path, None, [], [])
    with pytest.raises(NotCachedError, match="neither in eval/cache nor with photos"):
        await run(db_pool, FakeVision(), [empty], live=True)


def test_test_split_has_every_group_and_out_of_scope_is_apart():
    units = collect_units("test")
    groups = {u.group for u in units}
    assert groups == {"synthetic", "real", "semi", "out_of_scope"}
    assert not any(u.in_trust_number for u in units if u.group == "out_of_scope")
    for semi in (u for u in units if u.group == "semi"):
        # just the recipe's violation: the label's own are counted once, on the base case
        assert semi.spec_file and [v["rule_id"] for v in semi.violations] == ["ALG-SPEC-MISSING"]
    assert {u.group for u in collect_units("dev")} == {"synthetic"}  # real photos: test only


async def test_the_file_cache_reproduces_without_db_photos_or_key(db_pool, units, tmp_path):
    vision = FakeVision([truth_of(u) for u in units])
    first = await run(db_pool, vision, units, live=True)
    await db_pool.execute("TRUNCATE extraction_cache")
    clones = []  # a clean clone of the real set: truth and recipes, no photos
    for unit in units:
        folder = tmp_path / "clone" / unit.case
        folder.mkdir(parents=True)
        if unit.spec_file:
            shutil.copy(unit.folder / unit.spec_file, folder / unit.spec_file)
        clones.append(dataclasses.replace(unit, folder=folder))
    again = await run(db_pool, FakeVision(), clones, live=False)
    assert [r["verdict"] for r in again] == [r["verdict"] for r in first]
    assert [r["findings"] for r in again] == [r["findings"] for r in first]
    data = json.loads((cache_root_of() / "dev" / f"{units[0].case}.json").read_text())
    assert set(data) == {
        "case", "model", "prompt_version", "photo_sha256", "usage", "extraction", "raw_text"
    }  # fmt: skip
    assert data["model"] == "fake/fake" and len(data["photo_sha256"]) == len(units[0].photos())


async def test_a_file_cache_for_other_photos_or_model_is_not_used(db_pool, units):
    vision = FakeVision([truth_of(u) for u in units[:1]])
    await run(db_pool, vision, units[:1], live=True)
    await db_pool.execute("TRUNCATE extraction_cache")
    path = cache_root_of() / "dev" / f"{units[0].case}.json"
    data = json.loads(path.read_text())
    path.write_text(json.dumps(data | {"photo_sha256": ["0" * 64]}))  # the photos changed
    with pytest.raises(NotCachedError, match=units[0].case):
        await run(db_pool, FakeVision(), units[:1], live=False)
    path.write_text(json.dumps(data | {"model": "gemini/other"}))
    with pytest.raises(NotCachedError, match=units[0].case):
        await run(db_pool, FakeVision(), units[:1], live=False)


def cache_root_of():
    import eval.run

    return eval.run.CACHE
