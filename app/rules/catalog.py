"""rule_id -> title and legal reference. Every finding takes its legal_ref from here."""

from typing import NamedTuple

from app.schemas import Evidence, Finding, Status


class RuleInfo(NamedTuple):
    title: str
    legal_ref: str


# Article numbers of Law 2639-VIII are not verified yet (TODO, docs/NOTES.md): the EU
# regulation it transposes is cited precisely. Order 1145 reproduces the annex of Reg.
# 1924/2006; its full text was not reachable when the thresholds were written (TODO).
_LAW = "Закон України № 2639-VIII «Про інформацію для споживачів щодо харчових продуктів»"
_ORDER = "Наказ МОЗ № 1145 від 15.05.2020, перелік тверджень про поживну цінність"
_SERVICE = "Вимога сервісу (без неї перевірку не виконати), не норма закону"


def _claim(title: str) -> RuleInfo:
    return RuleInfo(f"Твердження «{title}»", f"{_ORDER}; Регл. (ЄС) 1924/2006, додаток")


RULES: dict[str, RuleInfo] = {
    # general
    "IMG-QUALITY": RuleInfo("Фото придатне для читання", _SERVICE),
    "LABEL-MISSING": RuleInfo(
        "На фото є склад і таблиця поживної цінності",
        f"{_LAW} (обов'язкова інформація); Регл. (ЄС) 1169/2011 ст. 9(1)(b), 9(1)(l), ст. 30(1), "
        "ст. 32(1), дод. XV",
    ),
    "LABEL-TRUNCATED": RuleInfo(
        "Склад прочитано повністю",
        f"{_LAW} (перелік інгредієнтів); Регл. (ЄС) 1169/2011 ст. 9(1)(b), ст. 18",
    ),
    "SIDE-FRONT-MISSING": RuleInfo("Є фото лицьового боку (твердження)", _SERVICE),
    "NUT-PER": RuleInfo(
        "Таблиця на 100 г / 100 мл",
        "Регл. (ЄС) 1169/2011 ст. 32(2); Регл. (ЄС) 1924/2006, додаток (умови на 100 г / 100 мл)",
    ),
    # allergens
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
    # nutrition claims
    "sugar_free": _claim("без цукру"),
    "low_sugar": _claim("низький вміст цукру"),
    "no_added_sugar": _claim("без доданого цукру"),
    "protein_source": _claim("джерело білка"),
    "protein_high": _claim("високий вміст білка"),
    "fat_low": _claim("низький вміст жиру"),
    "fat_free": _claim("без жиру"),
    "satfat_low": _claim("низький вміст насичених жирів"),
    "fibre_source": _claim("джерело клітковини"),
    "fibre_high": _claim("високий вміст клітковини"),
    "salt_low": _claim("низький вміст солі"),
    "salt_very_low": _claim("дуже низький вміст солі"),
    "energy_low": _claim("низька енергетична цінність"),
    "CLAIM-UNVERIFIABLE": RuleInfo(
        "Твердження поза автоматичною перевіркою",
        "Наказ МОЗ № 1145 від 15.05.2020; Регл. (ЄС) 1924/2006 ст. 5, 8, 9 (порівняльні), "
        "10 (користь для здоров'я)",
    ),
    # nutrition consistency
    "NUT-ENERGY": RuleInfo(
        "Енергетична цінність відповідає нутрієнтам",
        "Регл. (ЄС) 1169/2011 ст. 31(1), дод. XIV (коефіцієнти перерахунку)",
    ),
    "NUT-KJ": RuleInfo(
        "кДж відповідають ккал", "Регл. (ЄС) 1169/2011 дод. XIV (1 ккал = 4,184 кДж)"
    ),
    "NUT-SUBSETS": RuleInfo(
        "Цукри ≤ вуглеводи, насичені ≤ жири",
        "Регл. (ЄС) 1169/2011 ст. 30(1), дод. XV («з них»)",
    ),
    "NUT-SPEC": RuleInfo(
        "Таблиця відповідає рецептурі",
        "Регл. (ЄС) 1169/2011 ст. 31(4); настанова ЄК щодо допусків для маркування поживної "
        "цінності (2012)",
    ),
}


def finding(
    rule_id: str,
    target: str | None,
    status: Status,
    message: str,
    photo_index: int | None = None,
    fragment: str | None = None,
    values: dict[str, float | str | None] | None = None,
    threshold: float | str | None = None,
) -> Finding:
    """A Finding with the catalog's legal_ref; no evidence object when there is nothing."""
    parts = (photo_index, fragment, values, threshold)
    evidence = None
    if any(p is not None for p in parts):
        evidence = Evidence(
            photo_index=photo_index, fragment=fragment, values=values, threshold=threshold
        )
    return Finding(
        rule_id=rule_id,
        target=target,
        status=status,
        message=message,
        evidence=evidence,
        legal_ref=RULES[rule_id].legal_ref,
    )
