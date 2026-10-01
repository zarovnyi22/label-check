"""Claims, nutrition consistency, general rules, the engine and GET /rules.

Extractions are built by `label()` (a complete, clean label) with overrides: the synthetic
generator with truth.json comes in B4a, then these move onto it.
"""

import pytest

from app.rules.catalog import RULES
from app.rules.claims import CLAIM_PATTERNS, find_claims
from app.rules.engine import RULES_VERSION, run_rules, verdict_of
from app.schemas import Finding, LabelExtraction, ProductSpec
from tests.conftest import make_client
from tests.spike_outputs import P02, P03, P16, P17

TABLE = {
    "per": "100g",
    "energy": "1650 кДж / 395 ккал",
    "fat": "10 г",
    "saturates": "2 г",
    "carbs": "60 г",
    "sugars": "3,1 г",
    "fibre": "7 г",
    "protein": "12 г",
    "salt": "0,3 г",
    "photo_index": 1,
}  # 4·60 + 4·12 + 9·10 + 2·7 = 392 kcal; 395 × 4.184 = 1652.7 kJ


def label(
    claims: list[str] | None = None,
    ingredients: str | None = "**вівсяні** пластівці, **молоко** сухе, підсолоджувач",
    sides: tuple[str, ...] = ("front", "back"),
    quality: str = "ok",
    **table,
) -> LabelExtraction:
    nutrition = None if table.get("nutrition") is False else TABLE | table
    return LabelExtraction.model_validate(
        {
            "photos": [{"index": i, "side": s, "quality": quality} for i, s in enumerate(sides)],
            "emphasis_resolvable": True,
            "ingredients_marked": {"text": ingredients, "photo_index": 1} if ingredients else None,
            "nutrition": nutrition,
            "other_text": [{"text": c, "photo_index": 0} for c in claims or []],
        }
    )


def rule(findings: list[Finding], rule_id: str, target: str | None = None) -> Finding:
    (found,) = [f for f in findings if f.rule_id == rule_id and f.target == target]
    return found


def claim(text: str, spec: ProductSpec | None = None, **table) -> Finding:
    findings, _ = run_rules(label([text], **table), spec)
    claim_ids = [f for f in findings if f.rule_id in CLAIM_PATTERNS]
    assert len(claim_ids) == 1, [f.rule_id for f in claim_ids]
    return claim_ids[0]


# --- finding claims ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "claim_id"),
    [
        ("БЕЗ ЦУКРУ", "sugar_free"),
        ("Sugar-free", "sugar_free"),
        ("не містить цукру", "sugar_free"),
        ("низький вміст цукру", "low_sugar"),
        ("Без доданого цукру", "no_added_sugar"),
        ("no added sugar", "no_added_sugar"),
        ("Джерело білка", "protein_source"),
        ("source of protein", "protein_source"),
        ("Високий вміст протеїну", "protein_high"),
        ("низький вміст жиру", "fat_low"),
        ("Знежирений", "fat_free"),
        ("0% жиру", "fat_free"),
        ("низький вміст насичених жирів", "satfat_low"),
        ("джерело клітковини", "fibre_source"),
        ("High fibre", "fibre_high"),
        ("низький вміст солі", "salt_low"),
        ("дуже низький вміст натрію", "salt_very_low"),
        ("низькокалорійний", "energy_low"),
    ],
)
def test_claims_are_found_by_code(text, claim_id):
    claims, _ = find_claims(label([text]))
    assert list(claims) == [claim_id]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("на 30 % менше цукру", "comparative"),
        ("Light", "comparative"),
        ("Корисно для травлення", "health"),
        ("З НАТУРАЛЬНИМИ ІНГРЕДІЄНТАМИ*", "unregulated"),  # spike p02
        ("Без консервантів", "unregulated"),
        ("без солі", "nutrition_other"),
        ("джерело кальцію", "nutrition_other"),
    ],
)
def test_unverifiable_wording(text, kind):
    claims, unverifiable = find_claims(label([text]))
    assert claims == {}
    assert list(unverifiable) == [kind]


@pytest.mark.parametrize(
    "text",
    [
        "Містить природні цукри",  # the required statement, not a claim
        "НАПІЙ … З ЦУКРОМ ТА ПІДСОЛОДЖУВАЧАМИ",
        "Лінія підтримки споживачів: 0-800-300-970.",
        "МІСТИТЬ АЛЬПІЙСЬКЕ МОЛОКО",
    ],
)
def test_no_claim(text):
    assert find_claims(label([text])) == ({}, {})


def test_no_added_sugar_is_not_sugar_free_and_very_low_is_not_low():
    claims, _ = find_claims(label(["без доданого цукру", "дуже низький вміст солі"]))
    assert list(claims) == ["no_added_sugar", "salt_very_low"]


def test_same_claim_twice_is_one_finding():
    findings, _ = run_rules(label(["БЕЗ ЦУКРУ", "Sugar free"], sugars="0,2 г"), None)
    found = [f for f in findings if f.rule_id == "sugar_free"]
    assert len(found) == 1
    assert found[0].evidence.fragment == "БЕЗ ЦУКРУ; Sugar free"


# --- thresholds ------------------------------------------------------------------------------


def test_sugar_free_violation_with_code_numbers():
    f = claim("БЕЗ ЦУКРУ")  # sugars "3,1 г"
    assert f.status == "violation"
    assert f.target == "sugar_free"
    assert f.evidence.values == {"sugars": 3.1}
    assert f.evidence.threshold == 0.5
    assert "3,1" in f.message and "0,5" in f.message


@pytest.mark.parametrize(
    ("sugars", "status"),
    [
        ("0,5 г", "pass"),  # exactly at the threshold
        ("0,51 г", "violation"),
        ("<0,5 г", "pass"),
        ("<1 г", "needs_review"),  # could be 0.3 or 0.9
        ("сліди", "needs_review"),
        ("н/д", "needs_review"),
        (None, "needs_review"),
    ],
)
def test_sugar_free(sugars, status):
    assert claim("без цукру", sugars=sugars).status == status


@pytest.mark.parametrize(
    ("per", "sugars", "status"),
    [
        ("100g", "5 г", "pass"),
        ("100g", "5,1 г", "violation"),
        ("100ml", "2,5 г", "pass"),
        ("100ml", "3 г", "violation"),  # 3 g is low for a solid, not for a drink
    ],
)
def test_low_sugar_solid_vs_liquid(per, sugars, status):
    assert claim("низький вміст цукру", per=per, sugars=sugars).status == status


def test_form_from_spec_overrides_table_basis():
    spec = ProductSpec(form="liquid")
    assert claim("низький вміст цукру", spec, per="100g", sugars="3 г").status == "violation"


@pytest.mark.parametrize(
    ("text", "field", "value", "status"),
    [
        ("низький вміст жиру", "fat", "3 г", "pass"),
        ("низький вміст жиру", "fat", "3,5 г", "violation"),
        ("без жиру", "fat", "0,5 г", "pass"),
        ("без жиру", "fat", "1 г", "violation"),
        ("низький вміст солі", "salt", "0,3 г", "pass"),
        ("низький вміст солі", "salt", "0,31 г", "violation"),
        ("дуже низький вміст солі", "salt", "0,1 г", "pass"),
        ("дуже низький вміст солі", "salt", "0,2 г", "violation"),
    ],
)
def test_max_claims_at_threshold(text, field, value, status):
    assert claim(text, **{field: value}).status == status


@pytest.mark.parametrize(
    ("energy", "per", "status"),
    [
        ("167 кДж / 40 ккал", "100g", "pass"),
        ("172 кДж / 41 ккал", "100g", "violation"),
        ("84 кДж / 20 ккал", "100ml", "pass"),
        ("105 кДж / 25 ккал", "100ml", "violation"),
    ],
)
def test_energy_low(energy, per, status):
    assert claim("низькокалорійний", energy=energy, per=per).status == status


@pytest.mark.parametrize(
    ("protein", "kcal", "text", "status"),
    [
        ("3 г", "100", "джерело білка", "pass"),  # 3·4 / 100 = 12 % exactly
        ("2,9 г", "100", "джерело білка", "violation"),
        ("5 г", "100", "високий вміст білка", "pass"),  # 20 %
        ("4,9 г", "100", "високий вміст білка", "violation"),
        ("<2,9 г", "100", "джерело білка", "violation"),  # below 12 % whatever it is
        ("<3 г", "100", "джерело білка", "needs_review"),  # "lt" also means "≤": may be 12 %
        ("<5 г", "100", "джерело білка", "needs_review"),
    ],
)
def test_protein_share_of_energy(protein, kcal, text, status):
    f = claim(text, protein=protein, energy=f"{kcal} ккал")
    assert f.status == status
    assert f.evidence.values["kcal"] == float(kcal)


@pytest.mark.parametrize(
    ("fibre", "energy", "text", "status"),
    [
        ("3 г", "395 ккал", "джерело клітковини", "pass"),
        ("2 г", "100 ккал", "джерело клітковини", "pass"),  # 2 g / 100 kcal >= 1.5
        ("2 г", "395 ккал", "джерело клітковини", "violation"),
        ("6 г", "395 ккал", "високий вміст клітковини", "pass"),
        ("5 г", "395 ккал", "високий вміст клітковини", "violation"),
        ("2 г", None, "джерело клітковини", "needs_review"),  # per 100 kcal unknown
    ],
)
def test_fibre(fibre, energy, text, status):
    assert claim(text, fibre=fibre, energy=energy).status == status


@pytest.mark.parametrize(
    ("saturates", "energy", "per", "status"),
    [
        ("1,5 г", "395 ккал", "100g", "pass"),  # 13.5 kcal = 3.4 %
        ("1,6 г", "395 ккал", "100g", "violation"),
        ("1,5 г", "100 ккал", "100g", "violation"),  # 13.5 % of energy
        ("0,75 г", "200 ккал", "100ml", "pass"),
        ("0,8 г", "200 ккал", "100ml", "violation"),
    ],
)
def test_satfat_low(saturates, energy, per, status):
    assert (
        claim("низький вміст насичених жирів", saturates=saturates, energy=energy, per=per).status
        == status
    )


def test_claim_without_table_or_per_portion_needs_review():
    assert claim("без цукру", nutrition=False).status == "needs_review"
    f = claim("без цукру", per="portion", sugars="0,1 г")
    assert f.status == "needs_review"
    assert "NUT-PER" in f.message


def test_threshold_by_form_unknown_needs_review():
    assert claim("низький вміст цукру", per=None, sugars="1 г").status == "needs_review"


# --- no added sugar --------------------------------------------------------------------------


def test_no_added_sugar_with_honey_is_violation():
    findings, _ = run_rules(
        label(["Без доданого цукру"], ingredients="вівсяні пластівці, мед"), None
    )
    f = rule(findings, "no_added_sugar", "no_added_sugar")
    assert f.status == "violation"
    assert "мед" in f.message


@pytest.mark.parametrize(
    "ingredients",
    ["сироп глюкозний, какао", "пластівці, декстроза", "пластівці, цукор тростинний"],
)
def test_no_added_sugar_with_sugars_in_list(ingredients):
    findings, _ = run_rules(label(["без доданого цукру"], ingredients=ingredients), None)
    assert rule(findings, "no_added_sugar", "no_added_sugar").status == "violation"


def test_no_added_sugar_needs_the_natural_sugars_statement():
    without, _ = run_rules(label(["без доданого цукру"], sugars="12 г"), None)
    assert rule(without, "no_added_sugar", "no_added_sugar").status == "violation"
    with_it, _ = run_rules(
        label(["без доданого цукру", "Містить природні цукри"], sugars="12 г"), None
    )
    assert rule(with_it, "no_added_sugar", "no_added_sugar").status == "pass"
    # The statement itself is not an "unregulated" claim.
    assert not [f for f in with_it if f.rule_id == "CLAIM-UNVERIFIABLE"]


def test_no_added_sugar_truncated_list_needs_review():
    findings, _ = run_rules(label(["без доданого цукру"], ingredients="пластівці, мол[…]"), None)
    assert rule(findings, "no_added_sugar", "no_added_sugar").status == "needs_review"


# --- nutrition consistency ---------------------------------------------------------------


def test_clean_table_passes_consistency():
    findings, _ = run_rules(label(), None)
    for rule_id, target in [
        ("NUT-ENERGY", "energy"),
        ("NUT-KJ", "energy"),
        ("NUT-SUBSETS", "sugars"),
        ("NUT-SUBSETS", "saturates"),
    ]:
        assert rule(findings, rule_id, target).status == "pass"


@pytest.mark.parametrize(
    ("energy", "status"),
    [
        ("450 ккал", "pass"),  # 392 + 15 % = 450.8
        ("460 ккал", "needs_review"),
        ("334 ккал", "pass"),  # 392 - 15 % = 333.2
        ("333 ккал", "needs_review"),
    ],
)
def test_nut_energy(energy, status):
    findings, _ = run_rules(label(energy=energy), None)
    f = rule(findings, "NUT-ENERGY", "energy")
    assert f.status == status
    assert f.evidence.values["computed_kcal_min"] == 392


def test_nut_energy_small_values_use_10_kcal():
    # 4·2 + 4·1 + 9·0 = 12 kcal; 20 kcal is within ±10 kcal although +67 %.
    table = {"carbs": "2 г", "sugars": "1 г", "protein": "1 г", "fat": "0 г", "saturates": "0 г"}
    findings, _ = run_rules(label(energy="84 кДж / 20 ккал", fibre=None, **table), None)
    assert rule(findings, "NUT-ENERGY", "energy").status == "pass"


def test_nut_energy_with_trace_and_lt_uses_a_range():
    # Pepsi-like drink: 4·7 = 28 kcal; fat "<0,5" and protein "сліди" add at most 6.5 kcal.
    table = {
        "carbs": "7 г",
        "sugars": "7 г",
        "fat": "<0,5 г",
        "saturates": "0 г",
        "protein": "сліди",
    }
    findings, _ = run_rules(label(energy="146 кДж / 35 ккал", fibre=None, **table), None)
    f = rule(findings, "NUT-ENERGY", "energy")
    assert f.status == "pass"
    assert f.evidence.values["computed_kcal_min"] == 28


def test_nut_energy_missing_value_is_not_applicable_and_label_missing_reports_it():
    findings, verdict = run_rules(label(protein="н/д"), None)
    assert rule(findings, "NUT-ENERGY", "energy").status == "not_applicable"
    missing = rule(findings, "LABEL-MISSING", "nutrition")
    assert missing.status == "needs_review"
    assert "білки" in missing.message
    assert verdict == "needs_review"


@pytest.mark.parametrize(
    ("energy", "status"),
    [
        ("1653 кДж / 395 ккал", "pass"),
        ("1700 кДж / 395 ккал", "pass"),
        ("1750 кДж / 395 ккал", "needs_review"),
    ],
)
def test_nut_kj(energy, status):
    findings, _ = run_rules(label(energy=energy), None)
    assert rule(findings, "NUT-KJ", "energy").status == status


def test_nut_kj_without_kj():
    findings, _ = run_rules(label(energy="395 ккал"), None)
    assert rule(findings, "NUT-KJ", "energy").status == "not_applicable"


def test_nut_subsets():
    findings, _ = run_rules(label(sugars="61 г", saturates="11 г"), None)
    assert rule(findings, "NUT-SUBSETS", "sugars").status == "needs_review"
    assert rule(findings, "NUT-SUBSETS", "saturates").status == "needs_review"
    ok, _ = run_rules(label(sugars="60 г", saturates="<0,5 г"), None)
    assert rule(ok, "NUT-SUBSETS", "sugars").status == "pass"
    assert rule(ok, "NUT-SUBSETS", "saturates").status == "pass"


def recipe(**nutrition) -> ProductSpec:
    base = {
        "energy_kcal": 395,
        "fat": 10,
        "saturates": 2,
        "carbs": 60,
        "sugars": 3.1,
        "fibre": 7,
        "protein": 12,
        "salt": 0.3,
    }
    return ProductSpec(
        ingredients=[
            {"name": "молоко", "allergens": ["milk"]},
            {"name": "вівсяні пластівці", "allergens": ["cereals"]},
        ],
        nutrition_per_100=base | nutrition,
    )


def test_nut_spec():
    findings, _ = run_rules(label(), recipe())
    assert rule(findings, "NUT-SPEC").status == "pass"
    findings, _ = run_rules(label(), recipe(salt=1.0, sugars=4.9, fat=11.4))
    nut = {f.target: f.status for f in findings if f.rule_id == "NUT-SPEC"}
    # salt 0.3 vs 1.0 (±0.375) is off; sugars 3.1 vs 4.9 (±2) and fat 10 vs 11.4 (±2.28) fit.
    assert nut == {"salt": "needs_review"}


def test_nut_spec_without_recipe_numbers_is_not_checked():
    findings, _ = run_rules(label(), None)
    assert rule(findings, "NUT-SPEC").status == "not_checked"
    findings, _ = run_rules(label(per="portion"), recipe())
    assert rule(findings, "NUT-SPEC").status == "needs_review"


# --- general -----------------------------------------------------------------------------


def test_image_quality_flags_only_bad_photos():
    findings, _ = run_rules(label(quality="blurry"), None)
    flagged = [f for f in findings if f.rule_id == "IMG-QUALITY"]
    assert [(f.target, f.status) for f in flagged] == [
        ("photo_0", "needs_review"),
        ("photo_1", "needs_review"),
    ]
    clean, _ = run_rules(label(), None)
    assert not [f for f in clean if f.rule_id == "IMG-QUALITY"]  # "ok" is no pass


def test_label_missing():
    findings, verdict = run_rules(label(ingredients=None, nutrition=False), None)
    assert rule(findings, "LABEL-MISSING", "ingredients").status == "needs_review"
    assert rule(findings, "LABEL-MISSING", "nutrition").status == "needs_review"
    assert verdict == "needs_review"
    only_gap, _ = run_rules(label(ingredients="[…]"), None)
    assert rule(only_gap, "LABEL-MISSING", "ingredients").status == "needs_review"


def test_label_truncated():
    findings, _ = run_rules(label(ingredients="пластівці, **молоко**, сі[…]"), None)
    f = rule(findings, "LABEL-TRUNCATED", "ingredients")
    assert f.status == "needs_review"
    assert f.evidence.fragment == "сі[…]"
    assert rule(run_rules(label(), None)[0], "LABEL-TRUNCATED", "ingredients").status == "pass"


def test_side_front_missing():
    findings, verdict = run_rules(label(["без цукру"], sides=("back",), sugars="0 г"), None)
    assert rule(findings, "SIDE-FRONT-MISSING").status == "not_checked"
    assert rule(findings, "sugar_free", "sugar_free").status == "pass"  # still checked


@pytest.mark.parametrize(
    ("per", "status"),
    [
        ("100g", "pass"),
        ("100ml", "pass"),
        ("portion", "needs_review"),
        ("prepared", "needs_review"),
        (None, "needs_review"),
    ],
)
def test_nut_per(per, status):
    findings, _ = run_rules(label(per=per), None)
    assert rule(findings, "NUT-PER").status == status


# --- engine ------------------------------------------------------------------------------


def _f(status: str) -> Finding:
    return Finding(rule_id="X", status=status, message="", legal_ref="")


@pytest.mark.parametrize(
    ("statuses", "verdict"),
    [
        (["pass", "not_checked", "needs_review", "violation"], "fail"),
        (["pass", "not_checked", "needs_review"], "needs_review"),
        (["pass", "not_checked", "not_applicable"], "incomplete"),
        (["pass", "not_applicable"], "pass"),
    ],
)
def test_verdict_order(statuses, verdict):
    assert verdict_of([_f(s) for s in statuses]) == verdict


def test_clean_label_without_recipe_is_incomplete_not_pass():
    _, verdict = run_rules(label(), None)
    assert verdict == "incomplete"  # allergen completeness not checked without a recipe


def test_clean_label_with_recipe_passes():
    findings, verdict = run_rules(label(), recipe())
    assert verdict == "pass", [
        (f.rule_id, f.target, f.status) for f in findings if f.status != "pass"
    ]


def test_every_rule_in_findings_is_in_the_catalog():
    spikes = [LabelExtraction.model_validate_json(r) for r in (P02, P03, P16, P17)]
    labels = [label(["без цукру", "Light", "джерело білка", "без доданого цукру"]), *spikes]
    for ex in labels:
        for spec in (None, recipe()):
            for f in run_rules(ex, spec)[0]:
                assert f.legal_ref == RULES[f.rule_id].legal_ref


def test_catalog_covers_every_claim():
    assert set(CLAIM_PATTERNS) <= set(RULES)
    assert all(info.legal_ref for info in RULES.values())


@pytest.mark.parametrize("raw", [P02, P03, P16, P17])
def test_spike_answers_run_end_to_end(raw):
    findings, verdict = run_rules(LabelExtraction.model_validate_json(raw), None)
    assert verdict in ("needs_review", "incomplete", "fail")
    assert verdict != "pass"


def test_spike_p03_pepsi_table_is_consistent():
    findings, _ = run_rules(LabelExtraction.model_validate_json(P03), None)
    assert rule(findings, "NUT-ENERGY", "energy").status == "pass"  # 4·7 = 28 kcal
    assert rule(findings, "NUT-KJ", "energy").status == "pass"  # 28 × 4.184 = 117 ≈ 120
    assert rule(findings, "NUT-PER").status == "pass"


async def test_get_rules():
    async with make_client() as client:
        resp = await client.get("/rules")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rules_version"] == RULES_VERSION
    ids = {r["rule_id"] for r in body["rules"]}
    assert {"ALG-EMPH", "sugar_free", "CLAIM-UNVERIFIABLE", "NUT-ENERGY", "IMG-QUALITY"} <= ids
    assert all(r["legal_ref"] for r in body["rules"])
