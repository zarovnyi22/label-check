"""Rules on the truth (docs/SPEC.md §4): run_rules(truth.extraction, spec) of EVERY synthetic
case flags exactly truth.violations + truth.expected_flags. A miss here is a bug in the rules
or the generator, not the model.

oov cases (meta.oov: wording outside the dictionary on purpose) must differ only by those
words: with them added to the dictionary for the test, the match is exact again. The
dictionary itself is extended with dev forms only, never with test ones (NOTES, B4a).
"""

import json
import re

import pytest

from app.rules import allergens
from app.rules.allergen_dict import PATTERNS
from app.rules.claims import _CLAIM_RES, normalize
from app.rules.engine import run_rules
from app.schemas import LabelExtraction, ProductSpec
from eval.generate import ROOT, SPLITS, load_pool, plain_text

SHOWN = ("violation", "needs_review")
CASES = sorted((ROOT / "cases").glob("*/*/truth.json"))


def load(path):
    truth = json.loads(path.read_text(encoding="utf-8"))
    spec_path = path.with_name("spec.json")
    spec = ProductSpec.model_validate_json(spec_path.read_text()) if spec_path.exists() else None
    return truth, spec


def flagged(truth: dict, spec: ProductSpec | None) -> set[tuple[str, str | None]]:
    findings, _ = run_rules(LabelExtraction.model_validate(truth["extraction"]), spec)
    return {(f.rule_id, f.target) for f in findings if f.status in SHOWN}


def expected(truth: dict) -> set[tuple[str, str | None]]:
    return {(v["rule_id"], v["target"]) for v in truth["violations"] + truth["expected_flags"]}


def add_to_dictionary(monkeypatch, split: str, words: list[str]) -> None:
    """Teach the rules the oov words of a case: allergen terms, trap phrases, claim wording."""
    pool = load_pool(split)
    for word in words:
        category = next(
            (c for c, es in pool["allergens"].items() for e in es if plain_text(e["text"]) == word),
            None,
        )
        claim = next((c for c, ws in pool["claims"].items() if word in ws), None)
        if category:
            old = PATTERNS[category]
            new = re.compile(f"{old.pattern}|{re.escape(word)}", re.I)
            monkeypatch.setitem(PATTERNS, category, new)
        elif claim:
            old = _CLAIM_RES[claim]
            new = re.compile(f"{old.pattern}|{re.escape(normalize(word))}", re.I)
            monkeypatch.setitem(_CLAIM_RES, claim, new)
        else:
            assert word in [t["text"] for t in pool["traps"]], word
            phrase = re.compile(rf"(?P<x>{re.escape(word)})", re.I)
            masks = [*allergens.EXCLUSION_PATTERNS, phrase]
            monkeypatch.setattr(allergens, "EXCLUSION_PATTERNS", masks)


def test_all_cases_are_here():
    assert {p.parent.parent.name for p in CASES} == set(SPLITS) and len(CASES) >= 60


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.parent.name)
def test_rules_on_truth_flag_exactly_the_truth(path, monkeypatch):
    truth, spec = load(path)
    oov = truth["meta"]["oov"]
    if oov:
        add_to_dictionary(monkeypatch, path.parent.parent.name, oov)
    assert flagged(truth, spec) == expected(truth)


def test_the_oov_patch_is_needed_somewhere():
    """Guards the oov branch above: without the patch some oov case does differ."""
    differing = [
        p for p in CASES if (t := load(p)) and t[0]["meta"]["oov"] and flagged(*t) != expected(t[0])
    ]
    assert differing


# --- real photos (test only) + semi-synthetic recipes ------------------------------------------

# the main real set (Ukrainian labels) and the out-of-market group (informational)
REAL = sorted(p for d in ("real", "real_out_of_scope") for p in (ROOT / d).glob("*/truth.json"))


@pytest.mark.parametrize("path", REAL, ids=lambda p: p.parent.name)
def test_real_truth_is_valid(path):
    truth = json.loads(path.read_text(encoding="utf-8"))
    extraction = LabelExtraction.model_validate(truth["extraction"])
    assert extraction.model_dump() == truth["extraction"]
    assert truth["meta"]["synthetic"] is False
    for item in truth["violations"] + truth["expected_flags"]:
        assert set(item) == {"rule_id", "target"}
    assert 1 <= len(truth["spec_variants"]) <= 2


@pytest.mark.parametrize("path", REAL, ids=lambda p: p.parent.name)
def test_semi_synthetic_recipe_misses_exactly_one_allergen(path):
    """With the recipe, the allergen it adds is shown to the technologist (the known answer)."""
    truth = json.loads(path.read_text(encoding="utf-8"))
    for variant in truth["spec_variants"]:
        spec = ProductSpec.model_validate_json(path.with_name(variant["spec"]).read_text())
        (missing,) = variant["violations"]
        assert missing["rule_id"] == "ALG-SPEC-MISSING"
        assert (missing["rule_id"], missing["target"]) in flagged(truth, spec)
