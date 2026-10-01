"""rule_id -> title and legal reference. Every finding takes its legal_ref from here."""

from typing import NamedTuple


class RuleInfo(NamedTuple):
    title: str
    legal_ref: str


# Article numbers of Law 2639-VIII are not verified yet (TODO, docs/NOTES.md): the EU
# regulation it transposes is cited precisely.
_LAW = "Закон України № 2639-VIII «Про інформацію для споживачів щодо харчових продуктів»"

RULES: dict[str, RuleInfo] = {
    "ALG-EMPH": RuleInfo(
        "Алергени у складі виділені шрифтом",
        f"{_LAW} (виділення алергенів у переліку інгредієнтів); "
        "Регл. (ЄС) 1169/2011 ст. 21(1)(b), дод. II",
    ),
    "ALG-SPEC-MISSING": RuleInfo(
        "Алерген з рецептури зазначено на етикетці",
        f"{_LAW} (обов'язкове зазначення алергенів); "
        "Регл. (ЄС) 1169/2011 ст. 9(1)(c), ст. 21(1), дод. II",
    ),
    "ALG-SPEC-EXTRA": RuleInfo(
        "Алерген на етикетці є в рецептурі",
        f"{_LAW} (точність інформації); Регл. (ЄС) 1169/2011 ст. 7(1)",
    ),
    "ALG-MAY-CONTAIN": RuleInfo(
        "«Може містити» відповідає рецептурі",
        f"{_LAW} (добровільна інформація); Регл. (ЄС) 1169/2011 ст. 36(2), 36(3)(a)",
    ),
}


def legal_ref(rule_id: str) -> str:
    return RULES[rule_id].legal_ref
