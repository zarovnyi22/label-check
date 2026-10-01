"""The synthetic case generator (eval/generate.py): deterministic, both splits cover every
violation, the dev and test pools share no wording, the committed cases are its output."""

import json

import pytest

from app.schemas import LabelExtraction, ProductSpec
from eval.generate import (
    ROOT,
    SCENARIOS,
    SPLITS,
    VIOLATION_SCENARIOS,
    build_cases,
    load_pool,
    plain_text,
    render_case,
)

VIOLATION_RULES = {
    "ALG-EMPH",
    "sugar_free",
    "protein_source",
    "fat_low",
    "no_added_sugar",
    "NUT-ENERGY",
    "ALG-SPEC-MISSING",
    "LABEL-TRUNCATED",
}


@pytest.fixture(scope="module")
def cases():
    return {split: build_cases(split) for split in SPLITS}


def test_same_seed_same_cases_and_photos(cases):
    again = build_cases("dev")
    assert [(c.truth(), c.spec) for c in again] == [(c.truth(), c.spec) for c in cases["dev"]]
    picked = [c for c in again if c.quality in ("cropped", "rotate", "blur")][:3]
    first = {c.id: c for c in cases["dev"]}
    for case in picked:
        assert render_case(case) == render_case(first[case.id])


def test_another_seed_other_cases(cases):
    other = build_cases("dev", seed=7)
    assert [c.truth() for c in other] != [c.truth() for c in cases["dev"]]


@pytest.mark.parametrize("split", SPLITS)
def test_every_violation_type_is_in_both_splits(cases, split):
    found = {v["rule_id"] for c in cases[split] for v in c.violations}
    assert found == VIOLATION_RULES == set(VIOLATION_SCENARIOS)
    assert len(cases[split]) == sum(SCENARIOS.values())
    clean = [c for c in cases[split] if not c.violations]
    assert len(clean) >= 10
    qualities = {c.quality for c in cases[split]}
    assert qualities == {"clean", "blur", "rotate", "jpeg40", "cropped"}


def test_clean_cases_include_sugar_free_with_lt_sugars(cases):
    for split in SPLITS:
        lt = [c for c in cases[split] if c.scenario == "clean_sugar_free_lt"]
        assert lt and all(c.extraction["nutrition"]["sugars"] == "<0,5 г" for c in lt)
        assert all(not c.violations for c in lt)


def _wording(pool: dict) -> set[str]:
    texts = [e["text"] for entries in pool["allergens"].values() for e in entries]
    texts += [e["text"] for e in pool["traps"]]
    texts += pool["sweeteners"] + [pool["natural_sugars"], pool["may_contain"]]
    texts += [w for ws in pool["claims"].values() for w in ws]
    texts += [n for ns in pool["names"].values() for n in ns]
    texts += [f.lower() for f in pool["may_contain_forms"].values()]
    return {plain_text(t).lower() for t in texts}


def test_dev_and_test_pools_do_not_share_wording():
    dev, test = _wording(load_pool("dev")), _wording(load_pool("test"))
    assert dev and test
    assert dev & test == set()


@pytest.mark.parametrize("split", SPLITS)
def test_truth_is_a_valid_extraction_and_spec(cases, split):
    for case in cases[split]:
        extraction = LabelExtraction.model_validate(case.extraction)
        # nothing the schema would drop: the truth is exactly what the rules will read
        assert extraction.model_dump() == case.extraction
        if case.spec is not None:
            ProductSpec.model_validate(case.spec)
        assert case.truth()["meta"]["synthetic"] is True


def test_cropped_case_marks_the_cut_and_keeps_the_allergens(cases):
    cropped = [c for split in SPLITS for c in cases[split] if c.quality == "cropped"]
    assert len(cropped) >= 4
    for case in cropped:
        text = case.extraction["ingredients_marked"]["text"]
        assert text.endswith(" […]") and case.full_ingredients.startswith(text[:-4])
        assert len(text) - 4 < len(case.full_ingredients) - 1  # something is really cut
        assert case.extraction["photos"][1]["quality"] == "cropped"
        assert case.violations == [{"rule_id": "LABEL-TRUNCATED", "target": "ingredients"}]


def test_spec_missing_case_has_the_allergen_only_in_the_recipe(cases):
    for case in (c for s in SPLITS for c in cases[s] if c.scenario == "ALG-SPEC-MISSING"):
        (violation,) = case.violations
        recipe = {a for i in case.spec["ingredients"] for a in i["allergens"]}
        label_allergens = {
            a for i in case.spec["ingredients"] if i["name"] in case.full_ingredients.lower()
            for a in i["allergens"]
        }  # fmt: skip
        assert violation["target"] in recipe - label_allergens


@pytest.mark.parametrize("split", SPLITS)
def test_committed_cases_are_the_generator_output(cases, split):
    """eval/cases is never edited by hand: `make generate` reproduces every truth and spec."""
    folder = ROOT / "cases" / split
    assert sorted(p.name for p in folder.iterdir()) == [c.id for c in cases[split]]
    for case in cases[split]:
        truth = json.loads((folder / case.id / "truth.json").read_text(encoding="utf-8"))
        assert truth == case.truth()
        spec_path = folder / case.id / "spec.json"
        assert (json.loads(spec_path.read_text()) if spec_path.exists() else None) == case.spec
        photos = sorted(p.name for p in (folder / case.id).glob("photo_*.jpg"))
        assert len(photos) == len(case.extraction["photos"])
