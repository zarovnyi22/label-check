"""Semi-synthetic cases: a real photo + a recipe with a deliberate mismatch (docs/SPEC.md §4).

    python -m eval.semisynth                                     (make semisynth)

For every eval/real*/<id>/truth.json: 1–2 recipes spec_<k>.json = the label's own ingredients
+ ONE allergen the label does not have (meta.label_allergens / label_may_contain, set by the
human labeller). With that recipe the label really misses the allergen, so truth.spec_variants
gets {spec, violations: [ALG-SPEC-MISSING / <category>]} — added to truth.violations when the
case runs with that recipe. Deterministic by case id; rerunning rewrites the same files.
Real cases are test only.
"""

import json
import random
from pathlib import Path

from app.parsing import parse_ingredients
from app.schemas import AllergenCategory, ProductSpec
from eval.generate import write_json

# the main real set and the out-of-market group (informational, not in the trust number)
REAL_DIRS = [Path(__file__).resolve().parent / d for d in ("real", "real_out_of_scope")]
# The recipe ingredient that brings the missing allergen: its `allergens` declares it, so the
# name never decides (recipe_allergens reads both).
EXTRA: dict[AllergenCategory, str] = {
    "milk": "молоко коров'яче сухе",
    "eggs": "яйце куряче сушене",
    "cereals": "борошно пшеничне вищого сорту",
    "nuts": "ядра волоського горіха",
    "peanuts": "арахіс подрібнений",
    "soybeans": "соєвий білковий ізолят",
    "sesame": "кунжут білий",
    "mustard": "гірчичне насіння",
    "celery": "селера коренева сушена",
    "fish": "рибне борошно",
    "crustaceans": "креветки сушені",
    "molluscs": "кальмар сушений",
    "lupin": "люпинове борошно",
    "sulphites": "діоксид сірки E220",
}


def label_ingredients(extraction: dict) -> list[dict]:
    """The label's own list as recipe ingredients (top level, no markup)."""
    item = extraction.get("ingredients_marked") or {}
    ing = parse_ingredients(item.get("text"))
    names = [m.text.replace("**", "").strip(" .") for m in ing.mentions if m.depth == 0]
    return [{"name": n, "allergens": []} for n in names if n]


def variants(case_id: str, truth: dict) -> list[tuple[dict, AllergenCategory]]:
    meta = truth["meta"]
    present = set(meta.get("label_allergens", [])) | set(meta.get("label_may_contain", []))
    # a disputed allergen (meta.ambiguous, e.g. "ароматизатор гірчиці") is not "absent"
    present |= {a["target"] for a in meta.get("ambiguous", [])}
    absent = [c for c in EXTRA if c not in present]
    rng = random.Random(f"semisynth:{case_id}")
    out = []
    base = label_ingredients(truth["extraction"])
    nutrition = truth["extraction"].get("nutrition") or {}
    form = {"100g": "solid", "100ml": "liquid"}.get(nutrition.get("per"))
    for category in rng.sample(absent, min(rng.choice((1, 2)), len(absent))):
        at = rng.randrange(len(base) + 1)
        ingredients = [*base[:at], {"name": EXTRA[category], "allergens": [category]}, *base[at:]]
        spec = {"form": form, "ingredients": ingredients}
        spec["may_contain"] = sorted(meta.get("label_may_contain", []))
        ProductSpec.model_validate(spec)
        out.append((spec, category))
    return out


def main() -> None:
    cases = sorted(p.parent for real in REAL_DIRS for p in real.glob("*/truth.json"))
    for folder in cases:
        truth = json.loads((folder / "truth.json").read_text(encoding="utf-8"))
        for old in folder.glob("spec_*.json"):
            old.unlink()
        truth["spec_variants"] = []
        for k, (spec, category) in enumerate(variants(folder.name, truth), start=1):
            write_json(folder / f"spec_{k}.json", spec)
            truth["spec_variants"].append(
                {
                    "spec": f"spec_{k}.json",
                    "violations": [{"rule_id": "ALG-SPEC-MISSING", "target": category}],
                }
            )
        truth["meta"]["semi_synthetic"] = "spec_variants: recipe + one allergen not on the label"
        write_json(folder / "truth.json", truth)
    variants_total = sum(len(list(f.glob("spec_*.json"))) for f in cases)
    print(f"{len(cases)} real cases, {variants_total} semi-synthetic recipes")


if __name__ == "__main__":
    main()
