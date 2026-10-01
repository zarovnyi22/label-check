"""eval/run.py with FakeVision on 3 synthetic dev cases and the *_test database: cache only vs
live, pauses, a model error that does not stop the run, the test-split groups."""

import json

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
    assert not any(r["cache_hit"] for r in results)
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
    assert all(r["cache_hit"] for r in again) and len(vision.calls) == 3
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
    empty = Unit("x", "x", "real", tmp_path, None, [], [])
    with pytest.raises(NotCachedError, match="without photos"):
        await run(db_pool, FakeVision(), [empty], live=True)


def test_test_split_has_every_group_and_out_of_scope_is_apart():
    units = collect_units("test")
    groups = {u.group for u in units}
    assert groups == {"synthetic", "real", "semi", "out_of_scope"}
    assert not any(u.in_trust_number for u in units if u.group == "out_of_scope")
    for semi in (u for u in units if u.group == "semi"):
        assert semi.spec_file and semi.violations[-1]["rule_id"] == "ALG-SPEC-MISSING"
    assert {u.group for u in collect_units("dev")} == {"synthetic"}  # real photos: test only
