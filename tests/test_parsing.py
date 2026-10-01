"""parse_amount / parse_energy / parse_ingredients, incl. the real model answers of the spike."""

import json

import pytest

from app.parsing import Amount, Energy, parse_amount, parse_energy, parse_ingredients
from tests.spike_outputs import P02, P03, P16, P17


def emphasized(mention) -> list[str]:
    return [mention.text[s:e] for s, e in mention.emphasized_spans]


def upper(mention) -> list[str]:
    return [mention.text[s:e] for s, e in mention.upper]


# --- parse_amount ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0,5", Amount(0.5, "eq")),
        ("<0,5", Amount(0.5, "lt")),
        ("< 0,5 г", Amount(0.5, "lt")),
        ("≤0,5 г/g", Amount(0.5, "lt")),
        ("менше 0,5 г", Amount(0.5, "lt")),
        ("менше ніж 0,5 г", Amount(0.5, "lt")),
        ("less than 0.5 g", Amount(0.5, "lt")),
        ("сліди", Amount(None, "trace")),
        ("Сліди", Amount(None, "trace")),
        ("trace", Amount(None, "trace")),
        ("12.5 г", Amount(12.5, "eq")),
        ("12,5г.", Amount(12.5, "eq")),
        ("0", Amount(0.0, "eq")),
        ("0 г/g", Amount(0.0, "eq")),
        ("7,0 г (g)", Amount(7.0, "eq")),
        ("0,01 г (g)", Amount(0.01, "eq")),
        ("30,0 г/g", Amount(30.0, "eq")),
        ("18g/r", Amount(18.0, "eq")),  # the spike's reading of "18 г/g"
        ("  2,5 г  ", Amount(2.5, "eq")),
        ("500 мг", Amount(0.5, "eq")),
        ("120 mg", Amount(0.12, "eq")),
        ("120 мг/mg", Amount(0.12, "eq")),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "н/д",
        "-",
        "—",
        "[…]",
        "0,[…]",
        "0,5-1,0",  # a range
        "~5 г",
        "-1 г",
        "30 ккал",  # energy in a gram field
        "5 %",
        "5 мг/g",  # contradictory units
        "0,5 г 21%",  # value with %RI glued on
        "п'ять",
    ],
)
def test_parse_amount_unparsable_is_none_never_zero(text):
    assert parse_amount(text) is None


def test_milligrams_are_exact_decimals():
    # Decimal scaling, not float division: equal to the literal a threshold is written with.
    assert parse_amount("0,1 мг").value == 0.0001
    assert parse_amount("300 мг").value == 0.3
    assert parse_amount("0,3").value == 0.3


# --- parse_energy ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1760 кДж / 420 ккал", Energy(1760.0, 420.0)),
        ("1 760 кДж/420 ккал", Energy(1760.0, 420.0)),
        ("1760kJ/420kcal", Energy(1760.0, 420.0)),
        ("98 ккал / 418 кДж", Energy(418.0, 98.0)),
        ("418,5 кДж", Energy(418.5, None)),
        ("420 ккал", Energy(None, 420.0)),
        ("1760 / 420", Energy(None, None)),
        ("<4 кДж / <1 ккал", Energy(None, None)),
        ("1760 кДж / 420 ккал; 352 кДж / 84 ккал", Energy(None, None)),  # two columns
        ("н/д", Energy(None, None)),
        ("", Energy(None, None)),
        (None, Energy(None, None)),
    ],
)
def test_parse_energy(text, expected):
    assert parse_energy(text) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(P02, Energy(418.0, 98.0)), (P03, Energy(120.0, 28.0)), (P17, Energy(2222.0, 532.0))],
)
def test_parse_energy_on_spike_output(raw, expected):
    assert parse_energy(json.loads(raw)["nutrition"]["energy"]) == expected


def test_parse_amount_on_spike_output():
    p02 = json.loads(P02)["nutrition"]
    assert parse_amount(p02["fat"]) == Amount(0.2, "eq")  # "0,2 г/g"
    assert parse_amount(p02["salt"]) == Amount(2.5, "eq")
    p03 = json.loads(P03)["nutrition"]
    assert parse_amount(p03["sugars"]) == Amount(7.0, "eq")  # "7,0 г (g)"
    assert parse_amount(p03["fibre"]) is None  # null in the answer: not on the label
    p17 = json.loads(P17)["nutrition"]
    assert parse_amount(p17["salt"]) == Amount(0.29, "eq")


# --- parse_ingredients -----------------------------------------------------------------------


def test_emphasis_inside_a_phrase():
    (m,) = parse_ingredients("сухе **молоко**").mentions
    assert m.text == "сухе молоко"
    assert emphasized(m) == ["молоко"]
    assert m.is_emphasized(5, 11)
    assert not m.is_emphasized(0, 4)


def test_uppercase_word_is_found_by_code():
    first, second = parse_ingredients("МОЛОКО коров'яче, сіль").mentions
    assert upper(first) == ["МОЛОКО"]
    assert emphasized(first) == []
    assert first.is_emphasized(0, 6)
    assert upper(second) == []


def test_uppercase_needs_two_letters_and_all_capitals():
    (m,) = parse_ingredients("Е 476 Молоко КЕШ'Ю").mentions
    assert upper(m) == ["КЕШ'Ю"]  # "Е" is one letter, "Молоко" is title case


def test_nested_brackets_give_depth():
    ing = parse_ingredients(
        "шоколад (цукор, какао-масло, емульгатор (лецитин **соєвий**)), **молоко**"
    )
    got = [(m.depth, m.text, emphasized(m)) for m in ing.mentions]
    assert got == [
        (0, "шоколад", []),
        (1, "цукор", []),
        (1, "какао-масло", []),
        (1, "емульгатор", []),
        (2, "лецитин соєвий", ["соєвий"]),
        (0, "молоко", ["молоко"]),
    ]


def test_unbalanced_closing_bracket_does_not_go_negative():
    ing = parse_ingredients("цукор), сіль (вода")
    assert [(m.depth, m.text) for m in ing.mentions] == [(0, "цукор"), (0, "сіль"), (1, "вода")]


@pytest.mark.parametrize(
    "marked",
    ["**молоко, сіль", "молоко**, сіль", "**молоко** сухе, **сіль", "молоко***, сіль"],
)
def test_unclosed_marks_do_not_break_and_add_no_emphasis(marked):
    ing = parse_ingredients(marked)
    texts = [m.text for m in ing.mentions]
    assert texts[-1] == "сіль"
    assert all("*" not in t for t in texts)
    assert emphasized(ing.mentions[-1]) == []  # never emphasis by accident


def test_odd_marks_keep_the_balanced_pairs():
    first, second = parse_ingredients("**молоко** сухе, **сіль").mentions
    assert emphasized(first) == ["молоко"]
    assert emphasized(second) == []


def test_bold_italic_markup():
    (m, _) = parse_ingredients("***молоко***, цукор, сіль, вода").mentions[:2]
    assert m.text == "молоко"
    assert emphasized(m) == ["молоко"]


def test_emphasis_across_a_separator_is_split_per_mention():
    first, second, third, *_ = parse_ingredients("**молоко, яйця**, сіль, цукор, вода").mentions
    assert emphasized(first) == ["молоко"]
    assert emphasized(second) == ["яйця"]
    assert emphasized(third) == []


def test_all_caps_list_is_body_text_not_emphasis():
    ing = parse_ingredients("ЦУКОР, БОРОШНО ПШЕНИЧНЕ, МОЛОКО СУХЕ, сіль")
    assert ing.upper_is_body
    assert all(m.upper == () for m in ing.mentions)


def test_fully_marked_list_is_body_text_not_emphasis():
    ing = parse_ingredients("**цукор, борошно пшеничне, молоко сухе**")
    assert ing.marks_are_body
    assert all(m.emphasized_spans == () for m in ing.mentions)


def test_decimal_comma_and_sentence_end():
    ing = parse_ingredients("какао 7,5 %, ароматизатор. Мінімальний вміст какао 25 %.")
    assert [m.text for m in ing.mentions] == [
        "какао 7,5 %",
        "ароматизатор",
        "Мінімальний вміст какао 25 %",
    ]


@pytest.mark.parametrize(
    "marked",
    [
        "Склад: **молоко** сухе, сіль",
        "**Склад:** **молоко** сухе, сіль",
        "**Склад**: **молоко** сухе, сіль",
        "Склад : **молоко** сухе, сіль",
    ],
)
def test_list_title_is_dropped_without_eating_marks(marked):
    first, _ = parse_ingredients(marked).mentions
    assert first.text == "молоко сухе"
    assert emphasized(first) == ["молоко"]


@pytest.mark.parametrize(
    ("marked", "tail_start"),
    [
        ("цукор, **молоко**. Зберігати при температурі (18±3) °С.", "Зберігати"),
        ("цукор, **молоко**. Умови зберігання: сухе місце.", "Умови зберігання"),
        ("цукор, **молоко**. **Виробник**: ТОВ «Молочна ферма».", "**Виробник**"),
        ("цукор, **молоко**. Може містити горіхи.", "Може містити"),
        ("цукор, **молоко**. Може вміщувати арахіс.", "Може вміщувати"),
        ("цукор, **молоко**. Поживна цінність на 100 г: білки 3 г.", "Поживна цінність"),
        ("цукор, **молоко**. ДСТУ 4069.", "ДСТУ"),
        ("sugar, **milk**. Store in a dry place.", "Store"),
        ("sugar, **milk**. Nutrition facts per 100 g", "Nutrition facts"),
    ],
)
def test_text_after_storage_or_producer_is_not_ingredients(marked, tail_start):
    ing = parse_ingredients(marked)
    expected = ["sugar", "milk"] if marked.startswith("sugar") else ["цукор", "молоко"]
    assert [m.text for m in ing.mentions] == expected
    assert ing.tail.startswith(tail_start)


@pytest.mark.parametrize(
    "marked", ["дріжджі, сир (вироблено з **молока**)", "nutritional yeast, **milk**"]
)
def test_ingredient_words_do_not_end_the_list(marked):
    ing = parse_ingredients(marked)
    assert ing.tail is None
    assert any(emphasized(m) for m in ing.mentions)


def test_truncation_marker():
    ing = parse_ingredients("[…]укор, борошно **пшеничне**, сі[…]")
    assert ing.truncated
    assert [m.text for m in ing.mentions] == ["[…]укор", "борошно пшеничне", "сі[…]"]
    assert not parse_ingredients("цукор, сіль").truncated
    # A cut-off producer address is not a cut-off ingredient list.
    assert not parse_ingredients("цукор, сіль. Виробник: вул. Набереж[…]").truncated


@pytest.mark.parametrize("marked", [None, ""])
def test_no_ingredients(marked):
    ing = parse_ingredients(marked)
    assert ing.mentions == ()
    assert ing.tail is None
    assert not ing.truncated


# --- the spike's real answers --------------------------------------------------------------


def test_spike_p16_bold_italic_waffles():
    ing = parse_ingredients(json.loads(P16)["ingredients_marked"]["text"])
    assert ing.truncated  # "[…]укор": the cut-off "цукор" was not invented
    assert ing.tail is None
    marks = {m.text: emphasized(m) for m in ing.mentions}
    assert marks["борошно пшеничне"] == ["пшеничне"]
    assert marks["з молока"] == ["молока"]
    assert marks["молоко сухе знежирене"] == ["молоко"]
    assert marks["емульгатор соєвий лецитин"] == ["соєвий"]
    assert marks["молоко сухе незбиране"] == []  # bold on the photo, missed by the model
    assert marks["сіль"] == ["сіль"]  # not bold on the photo: the model's false mark
    depth = {m.text: m.depth for m in ing.mentions}
    assert depth["з молока"] == 1
    assert depth["гідрокарбонат натрію"] == 1
    assert ing.mentions[-1].text == "ароматизатор"


def test_spike_p17_list_boundary_is_not_trusted():
    ing = parse_ingredients(json.loads(P17)["ingredients_marked"]["text"])
    texts = [m.text for m in ing.mentions]
    assert texts[:3] == ["цукор", "какао-масло", "какао терте"]
    assert ("фундук", 1) in [(m.text, m.depth) for m in ing.mentions]
    # Storage, producer and the standard were glued to the list by the model: cut off.
    assert ing.tail.startswith("Зберігати при температурі")
    assert "Монделіз" in ing.tail
    assert not any("Виробник" in t or "Тростянець" in t or "ДСТУ" in t for t in texts)
    # Bold on the photo, but the model marked nothing (0 of 6).
    assert all(m.emphasized_spans == () and m.upper == () for m in ing.mentions)


def test_spike_p02_p03_lists_parse():
    p02 = parse_ingredients(json.loads(P02)["ingredients_marked"]["text"])
    assert p02.mentions[0].text == "вода питна"
    assert ("мускатний горіх", 1) in [(m.text, m.depth) for m in p02.mentions]
    p03 = parse_ingredients(json.loads(P03)["ingredients_marked"]["text"])
    assert ("сульфітно-аміачна карамель", 1) in [(m.text, m.depth) for m in p03.mentions]
    assert p03.mentions[-1].text == "ацесульфам калію та сукралоза"
