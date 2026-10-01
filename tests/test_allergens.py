"""Allergen dictionary and ALG-* rules.

Extractions are built from the spike's real model answers or with `extraction()` below:
the synthetic generator with truth.json comes in B4a (then rule tests move onto it).
"""

import json

import pytest

from app.rules.allergens import check_allergens, find_allergens
from app.rules.catalog import RULES
from app.schemas import LabelExtraction, ProductSpec
from tests.spike_outputs import P02, P03, P16, P17


def categories(text: str) -> list[str]:
    return sorted({h.category for h in find_allergens(text)})


def extraction(
    ingredients: str | None, resolvable: bool | None = True, may_contain: str | None = None
) -> LabelExtraction:
    return LabelExtraction.model_validate(
        {
            "emphasis_resolvable": resolvable,
            "ingredients_marked": {"text": ingredients, "photo_index": 1} if ingredients else None,
            "may_contain_text": {"text": may_contain, "photo_index": 1} if may_contain else None,
        }
    )


def spec(*allergens: str, may_contain: tuple[str, ...] = ()) -> ProductSpec:
    return ProductSpec(
        ingredients=[{"name": f"інгредієнт {a}", "allergens": [a]} for a in allergens]
        + [{"name": "цукор", "allergens": []}],
        may_contain=list(may_contain),
    )


def by_rule(findings, rule_id):
    return {f.target: f for f in findings if f.rule_id == rule_id}


# --- dictionary ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("сироватка суха молочна", ["milk"]),
        ("лактоза", ["milk"]),
        ("меланж", ["eggs"]),
        ("пшеничне борошно", ["cereals"]),
        ("борошно пшеничне", ["cereals"]),
        ("Wheat flour", ["cereals"]),
        ("МОЛОКО сухе", ["milk"]),
        ("масло вершкове", ["milk"]),
        ("сир твердий", ["milk"]),
        ("сирна начинка", ["milk"]),
        ("казеїнат натрію", ["milk"]),
        ("яєчний порошок", ["eggs"]),
        ("яйця курячі", ["eggs"]),
        ("борошно житнє", ["cereals"]),
        ("пластівці вівсяні", ["cereals"]),
        ("крупа ячмінна", ["cereals"]),
        ("лецитин соєвий", ["soybeans"]),
        ("соя", ["soybeans"]),
        ("сою", ["soybeans"]),
        ("арахіс смажений", ["peanuts"]),
        ("земляний горіх", ["peanuts"]),  # not tree nuts
        ("горіх земляний", ["peanuts"]),  # reversed order: a missed allergen otherwise
        ("горіхи земляні смажені", ["peanuts"]),
        ("ГОРІХИ ЗЕМЛЯНІ", ["peanuts"]),
        ("фундук", ["nuts"]),
        ("ядра горіха волоського", ["nuts"]),
        ("кеш'ю", ["nuts"]),
        ("кешʼю", ["nuts"]),
        ("мигдаль", ["nuts"]),
        ("hazelnuts", ["nuts"]),
        ("селера", ["celery"]),
        ("гірчиця", ["mustard"]),
        ("насіння кунжуту", ["sesame"]),
        ("консервант діоксид сірки", ["sulphites"]),
        ("метабісульфіт натрію", ["sulphites"]),
        ("консервант Е220", ["sulphites"]),
        ("E 224", ["sulphites"]),
        ("борошно люпину", ["lupin"]),
        ("філе риби", ["fish"]),
        ("рибний бульйон", ["fish"]),
        ("креветки", ["crustaceans"]),
        ("мідії", ["molluscs"]),
        ("cheese, milk powder, eggs", ["eggs", "milk"]),
    ],
)
def test_dictionary_finds(text, expected):
    assert categories(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "сироп глюкозний",  # "сир" is not "сироп"
        "сирий",
        "рибофлавін",  # "риб" is not riboflavin
        "кокосове молоко",
        "молоко кокосове",
        "рисове молоко",
        "вершки кокосові",
        "мускатний горіх",
        "горіх мускатний",
        "кокосовий горіх",
        "гречка",
        "какао-масло",
        "масло какао",
        "олія соняшникова",
        "масло соняшникове",
        "кислота молочна",
        "молочна кислота",
        "сульфітно-аміачна карамель",
        "сульфітно аміачна карамель",
        "глюконат міді",
        "Е 476",
        "E2200",
        "cocoa butter",
        "cream of tartar",
        "nutmeg",
        "кедровий горіх",  # pine nut: not in Annex II
        "горіхи кедрові",
        "pine nuts",
        "coconut",
        "lactic acid",
        "сіль, цукор, вода питна",
    ],
)
def test_dictionary_exclusions_and_substring_traps(text):
    assert categories(text) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("вівсяне молоко", ["cereals"]),  # oats yes, milk no
        ("соєве молоко", ["soybeans"]),
        ("мигдальне молоко", ["nuts"]),
        ("арахісове масло", ["peanuts"]),
        ("peanut butter", ["peanuts"]),
        ("coconut milk, milk", ["milk"]),  # the second "milk" is real
    ],
)
def test_plant_milks_keep_the_plant(text, expected):
    assert categories(text) == expected


def test_hit_offsets_point_at_the_word():
    (hit,) = find_allergens("борошно ПШЕНИЧНЕ")
    assert "борошно ПШЕНИЧНЕ"[hit.start : hit.end] == "ПШЕНИЧНЕ"


# --- ALG-EMPH --------------------------------------------------------------------------------


def test_emph_pass_on_marks_and_on_capitals():
    findings = check_allergens(extraction("сухе **молоко**, ЯЙЦЯ, цукор, сіль, вода"), None)
    emph = by_rule(findings, "ALG-EMPH")
    assert emph["milk"].status == "pass"
    assert emph["eggs"].status == "pass"
    assert emph["milk"].evidence.fragment == "сухе молоко"
    assert emph["milk"].evidence.photo_index == 1


@pytest.mark.parametrize("resolvable", [True, False, None])
def test_emph_missing_is_needs_review_never_violation(resolvable):
    findings = check_allergens(extraction("цукор, молоко сухе", resolvable), None)
    milk = by_rule(findings, "ALG-EMPH")["milk"]
    assert milk.status == "needs_review"
    assert "модель не підтвердила виділення" in milk.message
    assert milk.evidence.fragment == "молоко сухе"
    assert ("Фото не дозволяє розрізнити шрифт" in milk.message) is (resolvable is not True)
    assert not any(f.status == "violation" for f in findings if f.rule_id == "ALG-EMPH")


def test_emph_one_finding_per_category_listing_every_plain_mention():
    findings = check_allergens(extraction("**молоко**, вершки, цукор, сироватка, сіль"), None)
    emph = [f for f in findings if f.rule_id == "ALG-EMPH"]
    assert [f.target for f in emph] == ["milk"]
    assert emph[0].status == "needs_review"  # one plain mention is enough
    assert emph[0].evidence.fragment == "вершки; сироватка"


def test_emph_nested_clarification_counts():
    # The usual compliant form: the allergen named emphasized in brackets right after.
    text = "сироватковий пермеат (з **молока**), паста горіхова (**фундук**), цукор, сіль"
    emph = by_rule(check_allergens(extraction(text), None), "ALG-EMPH")
    assert emph["milk"].status == "pass"
    assert emph["nuts"].status == "pass"


def test_emph_clarification_must_be_nested_and_same_allergen():
    text = "сироватка, **молоко**, паста горіхова (**молоко**), цукор, сіль, вода"
    emph = by_rule(check_allergens(extraction(text), None), "ALG-EMPH")
    assert emph["milk"].status == "needs_review"  # "сироватка" is not inside the brackets
    assert emph["nuts"].status == "needs_review"  # milk does not clarify nuts


def test_may_contain_needs_no_emphasis():
    text = "цукор, **молоко**. Може містити горіхи, арахіс."
    findings = check_allergens(extraction(text), None)
    emph = by_rule(findings, "ALG-EMPH")
    assert set(emph) == {"milk"}
    assert emph["milk"].status == "pass"


def test_text_after_producer_is_not_checked():
    text = "цукор, **молоко**. Виробник: ТОВ «Молочна ферма», вул. Рибна, 1."
    assert set(by_rule(check_allergens(extraction(text), None), "ALG-EMPH")) == {"milk"}


def test_emph_all_caps_list_explains_why():
    findings = check_allergens(extraction("ЦУКОР, МОЛОКО СУХЕ, СІЛЬ"), None)
    milk = by_rule(findings, "ALG-EMPH")["milk"]
    assert milk.status == "needs_review"
    assert "великими літерами" in milk.message


def test_emph_no_allergens_is_not_applicable():
    emph = by_rule(check_allergens(extraction("цукор, вода, сіль"), None), "ALG-EMPH")
    assert list(emph) == [None]
    assert emph[None].status == "not_applicable"


def test_no_ingredients_gives_no_emph_finding():
    findings = check_allergens(extraction(None), None)
    assert "ALG-EMPH" not in {f.rule_id for f in findings}


# --- ALG-SPEC-MISSING / ALG-SPEC-EXTRA -------------------------------------------------------


def test_without_spec_completeness_is_not_checked():
    findings = check_allergens(extraction("цукор, **молоко**"), None)
    for rule_id in ("ALG-SPEC-MISSING", "ALG-SPEC-EXTRA", "ALG-MAY-CONTAIN"):
        (finding,) = [f for f in findings if f.rule_id == rule_id]
        assert finding.status == "not_checked"
        assert finding.target is None
        assert "Без рецептури" in finding.message


def test_spec_missing_violation_and_pass():
    findings = check_allergens(extraction("цукор, **молоко**, сіль, вода"), spec("milk", "eggs"))
    missing = by_rule(findings, "ALG-SPEC-MISSING")
    assert missing["milk"].status == "pass"
    assert missing["eggs"].status == "violation"
    assert "інгредієнт eggs" in missing["eggs"].message


def test_spec_missing_when_list_truncated_is_needs_review():
    findings = check_allergens(extraction("цукор, **молоко**, бо[…]"), spec("eggs"))
    assert by_rule(findings, "ALG-SPEC-MISSING")["eggs"].status == "needs_review"


def test_spec_missing_when_no_ingredients_is_needs_review():
    findings = check_allergens(extraction(None), spec("milk"))
    assert by_rule(findings, "ALG-SPEC-MISSING")["milk"].status == "needs_review"


def test_spec_missing_allergen_only_in_may_contain_is_still_missing():
    text = "цукор, какао. Може містити молоко."
    findings = check_allergens(extraction(text), spec("milk", may_contain=("milk",)))
    assert by_rule(findings, "ALG-SPEC-MISSING")["milk"].status == "violation"


def test_spec_without_allergens():
    findings = check_allergens(extraction("цукор, вода"), spec())
    assert by_rule(findings, "ALG-SPEC-MISSING")[None].status == "pass"
    assert by_rule(findings, "ALG-SPEC-EXTRA")[None].status == "pass"


def test_spec_extra():
    findings = check_allergens(extraction("цукор, **молоко**, **соєвий** лецитин"), spec("milk"))
    extra = by_rule(findings, "ALG-SPEC-EXTRA")
    assert set(extra) == {"soybeans"}
    assert extra["soybeans"].status == "needs_review"
    assert extra["soybeans"].evidence.fragment == "соєвий лецитин"


def test_spec_extra_pass():
    findings = check_allergens(extraction("цукор, **молоко**"), spec("milk"))
    assert by_rule(findings, "ALG-SPEC-EXTRA")[None].status == "pass"


# --- ALG-MAY-CONTAIN -------------------------------------------------------------------------


def test_may_contain_matches_spec():
    ex = extraction("цукор, **молоко**", may_contain="Може містити горіхи, арахіс.")
    findings = check_allergens(ex, spec("milk", may_contain=("nuts", "peanuts")))
    (finding,) = by_rule(findings, "ALG-MAY-CONTAIN").values()
    assert finding.status == "pass"
    assert finding.evidence.fragment == "Може містити горіхи, арахіс."


def test_may_contain_mismatch_both_ways():
    ex = extraction("цукор, **молоко**", may_contain="Може містити горіхи.")
    findings = check_allergens(ex, spec("milk", may_contain=("sesame",)))
    mc = by_rule(findings, "ALG-MAY-CONTAIN")
    assert {t: f.status for t, f in mc.items()} == {
        "nuts": "needs_review",
        "sesame": "needs_review",
    }


def test_may_contain_absent_everywhere_is_pass():
    findings = check_allergens(extraction("цукор, **молоко**"), spec("milk"))
    assert by_rule(findings, "ALG-MAY-CONTAIN")[None].status == "pass"


def test_may_contain_missing_on_label():
    findings = check_allergens(extraction("цукор, **молоко**"), spec("milk", may_contain=("nuts",)))
    nuts = by_rule(findings, "ALG-MAY-CONTAIN")["nuts"]
    assert nuts.status == "needs_review"
    assert "напису «може містити» на фото немає" in nuts.message


def test_may_contain_taken_from_the_list_tail():
    # The model glued "може містити" to the ingredients and left may_contain_text null.
    ex = extraction("цукор, **молоко**. Може містити **арахіс**. Зберігати в сухому місці.")
    findings = check_allergens(ex, spec("milk", may_contain=("peanuts",)))
    assert by_rule(findings, "ALG-MAY-CONTAIN")[None].status == "pass"


# --- the spike's real answers ----------------------------------------------------------------


def test_spike_p16_waffles():
    findings = check_allergens(LabelExtraction.model_validate_json(P16), None)
    emph = by_rule(findings, "ALG-EMPH")
    assert {t: f.status for t, f in emph.items()} == {
        "cereals": "pass",
        "soybeans": "pass",
        "milk": "needs_review",  # "молоко сухе незбиране": bold on the photo, missed
    }
    assert emph["milk"].evidence.fragment == "молоко сухе незбиране"


def test_spike_p16_may_contain_against_a_recipe():
    ex = LabelExtraction.model_validate_json(P16)
    recipe = spec("cereals", "milk", "soybeans", may_contain=("eggs", "nuts", "peanuts", "sesame"))
    findings = check_allergens(ex, recipe)
    assert by_rule(findings, "ALG-MAY-CONTAIN")[None].status == "pass"
    assert all(f.status == "pass" for f in by_rule(findings, "ALG-SPEC-MISSING").values())


def test_spike_p17_chocolate():
    findings = check_allergens(LabelExtraction.model_validate_json(P17), spec("milk"))
    emph = by_rule(findings, "ALG-EMPH")
    # Bold on the photo, 0 of 6 marked by the model: needs_review, not a false "fail".
    assert {t: f.status for t, f in emph.items()} == {
        "soybeans": "needs_review",
        "milk": "needs_review",
        "nuts": "needs_review",
    }
    assert set(by_rule(findings, "ALG-SPEC-EXTRA")) == {"soybeans", "nuts"}
    # "Може вміщувати … арахіс, інші горіхи, пшеницю".
    mc = by_rule(findings, "ALG-MAY-CONTAIN")
    assert set(mc) == {"cereals", "peanuts", "nuts"}


@pytest.mark.parametrize("raw", [P02, P03])
def test_spike_no_allergens_in_ketchup_and_cola(raw):
    # Ketchup: "мускатний горіх" is not a nut. Cola: "сульфітно-аміачна карамель" is E150d.
    findings = check_allergens(LabelExtraction.model_validate_json(raw), None)
    assert by_rule(findings, "ALG-EMPH")[None].status == "not_applicable"
    assert json.loads(raw)["ingredients_marked"]["text"]


def test_every_finding_rule_is_in_the_catalog():
    findings = check_allergens(LabelExtraction.model_validate_json(P17), spec("milk", "eggs"))
    for finding in findings:
        assert finding.legal_ref == RULES[finding.rule_id].legal_ref
        assert "1169/2011" in finding.legal_ref


# --- RR1 regressions -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("жовток яєчний сухий", ["eggs"]),
        ("жовтки", ["eggs"]),
        ("пахта", ["milk"]),
        ("масло топлене", ["milk"]),
        ("сколотини", ["milk"]),
        ("ghee", ["milk"]),
        ("крупа перлова", ["cereals"]),
        ("солод ячмінний", ["cereals"]),
        ("сухарі панірувальні", ["cereals"]),
        ("сардина атлантична", ["fish"]),
        ("філе хека", ["fish"]),
        ("шпроти", ["fish"]),
        ("sardines", ["fish"]),
        ("марципан", ["nuts"]),
        ("нуга", ["nuts"]),
        ("пиросульфіт натрію", ["sulphites"]),
    ],
)
def test_dictionary_rr1_additions(text, expected):
    assert categories(text) == expected


@pytest.mark.parametrize("text", ["солодкий перець", "жовтий барвник", "солодощі"])
def test_dictionary_rr1_traps(text):
    assert categories(text) == []


def test_spec_allergen_found_in_the_ingredient_name():
    # RR1 #4: "молоко сухе" without `allergens` is still milk.
    s = ProductSpec(ingredients=[{"name": "молоко сухе знежирене"}])
    findings = check_allergens(extraction("**вівсяні** пластівці, цукор"), s)
    assert by_rule(findings, "ALG-SPEC-MISSING")["milk"].status == "violation"
    assert "cereals" in by_rule(findings, "ALG-SPEC-EXTRA")


def test_spec_without_ingredients_is_not_checked():
    s = ProductSpec(form="solid")
    findings = check_allergens(extraction("рисові пластівці, цукор"), s)
    assert by_rule(findings, "ALG-SPEC-MISSING")[None].status == "not_checked"
    assert by_rule(findings, "ALG-SPEC-EXTRA")[None].status == "not_checked"


@pytest.mark.parametrize(
    ("recipe", "label"),
    [
        ("борошно пшеничне", "**вівсяні** пластівці, цукор"),
        ("фундук", "**мигдаль**, цукор"),
    ],
)
def test_spec_missing_compares_the_cereal_and_the_nut(recipe, label):
    # RR1 #5: Annex II names the cereal / nut; oats on the label do not declare wheat.
    category = "cereals" if "борошно" in recipe else "nuts"
    s = ProductSpec(ingredients=[{"name": recipe, "allergens": [category]}])
    f = by_rule(check_allergens(extraction(label), s), "ALG-SPEC-MISSING")[category]
    assert f.status == "needs_review"
    same = by_rule(check_allergens(extraction(f"**{recipe}**, цукор"), s), "ALG-SPEC-MISSING")
    assert same[category].status == "pass"


def test_gluten_is_not_the_cereal_name():
    # RR1 #6 / SPEC §2: "глютен" alone neither passes ALG-EMPH nor declares wheat.
    s = ProductSpec(ingredients=[{"name": "борошно пшеничне", "allergens": ["cereals"]}])
    findings = check_allergens(extraction("борошно, цукор, **глютен**"), s)
    assert by_rule(findings, "ALG-EMPH")["cereals"].status == "needs_review"
    assert by_rule(findings, "ALG-SPEC-MISSING")["cereals"].status == "needs_review"
    named = check_allergens(extraction("борошно **пшеничне**, цукор, сіль, **глютен**"), s)
    assert by_rule(named, "ALG-EMPH")["cereals"].status == "pass"
    assert by_rule(named, "ALG-SPEC-MISSING")["cereals"].status == "pass"


def test_may_contain_cut_off_is_needs_review():
    # RR1 #9a: "Може містити сліди […]" may hide the recipe's allergen.
    findings = check_allergens(
        extraction("рисові пластівці, цукор. Може містити сліди [...]"), spec()
    )
    assert by_rule(findings, "ALG-MAY-CONTAIN")[None].status == "needs_review"


def test_subtype_ignores_sweet_words_in_the_recipe():
    s = ProductSpec(
        ingredients=[
            {"name": "солод ячмінний", "allergens": ["cereals"]},
            {"name": "перець солодкий"},
        ]
    )
    f = by_rule(check_allergens(extraction("**солод** ячмінний, цукор"), s), "ALG-SPEC-MISSING")
    assert f["cereals"].status == "pass"
    # "солодкий" (sweet) is not malt: wheat in the recipe is still compared
    s = ProductSpec(ingredients=[{"name": "борошно пшеничне солодке", "allergens": ["cereals"]}])
    f = by_rule(check_allergens(extraction("**ячмінь**, цукор"), s), "ALG-SPEC-MISSING")
    assert "пшениця" in f["cereals"].message
