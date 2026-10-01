"""Nutrition table facts and consistency rules: NUT-ENERGY, NUT-KJ, NUT-SUBSETS, NUT-SPEC.

Consistency rules catch both label errors and misread photos, so a mismatch is needs_review,
never violation. A value that is missing or unreadable is not guessed: the NUT-* rule that
needs it is not_applicable and LABEL-MISSING (general.py) reports the field.
"""

import math
from dataclasses import dataclass

from app.parsing import Amount, parse_amount, parse_energy
from app.rules.catalog import finding
from app.schemas import Finding, LabelExtraction, Nutrition, Per, ProductSpec

NUTRIENTS = ("fat", "saturates", "carbs", "sugars", "fibre", "protein", "salt")
# Mandatory in the nutrition declaration (Reg. 1169/2011 art. 30(1)); fibre is voluntary.
MANDATORY = ("energy", "fat", "saturates", "carbs", "sugars", "protein", "salt")
NUTRIENT_NAMES_UK = {
    "energy": "енергетична цінність",
    "fat": "жири",
    "saturates": "насичені жири",
    "carbs": "вуглеводи",
    "sugars": "цукри",
    "fibre": "клітковина",
    "protein": "білки",
    "salt": "сіль",
}

# Reg. 1169/2011 Annex XIV conversion factors, kcal per gram.
KCAL_PER_G = {"carbs": 4, "protein": 4, "fat": 9, "fibre": 2}
KJ_PER_KCAL = 4.184
ENERGY_TOLERANCE = 0.15  # NUT-ENERGY: ±15 % of the computed energy …
ENERGY_TOLERANCE_KCAL = 10.0  # … or ±10 kcal, whichever is larger
KJ_TOLERANCE = 0.03  # NUT-KJ: ±3 %
# "сліди" carries no number; for the energy sum it is taken as 0 … this much, the usual
# "<0,5 г" declaration limit. Only a range for a sanity check, never a value for a claim.
TRACE_MAX_G = 0.5


@dataclass(frozen=True)
class NutritionFacts:
    per: Per | None
    photo_index: int | None
    kj: float | None
    kcal: float | None
    amounts: dict[str, Amount | None]  # NUTRIENTS -> parsed amount or None
    raw: dict[str, str | None]  # as printed, for evidence

    def unreadable(self) -> list[str]:
        """Mandatory fields that are missing or did not parse."""
        missing = [] if self.kcal is not None or self.kj is not None else ["energy"]
        return missing + [n for n in MANDATORY[1:] if self.amounts[n] is None]


def read_nutrition(nutrition: Nutrition | None) -> NutritionFacts | None:
    if nutrition is None:
        return None
    energy = parse_energy(nutrition.energy)
    raw = {n: getattr(nutrition, n) for n in ("energy", *NUTRIENTS)}
    return NutritionFacts(
        per=nutrition.per,
        photo_index=nutrition.photo_index,
        kj=energy.kj,
        kcal=energy.kcal,
        amounts={n: parse_amount(raw[n]) for n in NUTRIENTS},
        raw=raw,
    )


def fmt(value: float) -> str:
    """3.1 -> "3,1", 12.0 -> "12": numbers in messages as a Ukrainian label prints them."""
    return f"{value:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def at_least(value: float, minimum: float) -> bool:
    """value >= minimum, robust to float noise of computed values (energy shares, sums)."""
    return value >= minimum or math.isclose(value, minimum, rel_tol=1e-9)


def _bounds(amount: Amount) -> tuple[float, float]:
    """The range the true amount can be in."""
    if amount.qualifier == "trace":
        return 0.0, TRACE_MAX_G
    if amount.qualifier == "lt":
        return 0.0, amount.value
    return amount.value, amount.value


def check_energy(facts: NutritionFacts) -> list[Finding]:
    """NUT-ENERGY: declared kcal ≈ 4·carbs + 4·protein + 9·fat + 2·fibre (Annex XIV)."""
    parts = {n: facts.amounts[n] for n in ("carbs", "protein", "fat")}
    if facts.kcal is None or any(a is None for a in parts.values()):
        return [
            finding(
                "NUT-ENERGY",
                "energy",
                "not_applicable",
                "Енергетичну цінність не перевірено: потрібні ккал, жири, вуглеводи, білки "
                "(див. LABEL-MISSING).",
            )
        ]
    fibre = facts.amounts["fibre"]  # voluntary: absent -> 0 g fibre counted
    if fibre is not None:
        parts["fibre"] = fibre
    lo = sum(KCAL_PER_G[n] * _bounds(a)[0] for n, a in parts.items())
    hi = sum(KCAL_PER_G[n] * _bounds(a)[1] for n, a in parts.items())
    tol_lo = max(lo * ENERGY_TOLERANCE, ENERGY_TOLERANCE_KCAL)
    tol_hi = max(hi * ENERGY_TOLERANCE, ENERGY_TOLERANCE_KCAL)
    computed = fmt(lo) if lo == hi else f"{fmt(lo)}–{fmt(hi)}"
    values = {"kcal": facts.kcal, "computed_kcal_min": lo, "computed_kcal_max": hi}
    if lo - tol_lo <= facts.kcal <= hi + tol_hi:
        return [
            finding(
                "NUT-ENERGY",
                "energy",
                "pass",
                f"Енергетична цінність {fmt(facts.kcal)} ккал узгоджується з розрахунком за "
                f"нутрієнтами ({computed} ккал).",
                facts.photo_index,
                facts.raw["energy"],
                values,
            )
        ]
    return [
        finding(
            "NUT-ENERGY",
            "energy",
            "needs_review",
            f"Енергетична цінність {fmt(facts.kcal)} ккал не узгоджується з розрахунком за "
            f"нутрієнтами ({computed} ккал, допуск ±15 % або ±10 ккал): помилка етикетки або "
            "читання фото (поліоли/еритрит теж дають розбіжність) — перевірте таблицю.",
            facts.photo_index,
            facts.raw["energy"],
            values,
        )
    ]


def check_kj(facts: NutritionFacts) -> list[Finding]:
    """NUT-KJ: kJ ≈ kcal × 4.184 (±3 %)."""
    if facts.kj is None or facts.kcal is None:
        return [
            finding(
                "NUT-KJ",
                "energy",
                "not_applicable",
                "Не прочитано і кДж, і ккал — співвідношення не перевірено (див. LABEL-MISSING).",
            )
        ]
    expected = facts.kcal * KJ_PER_KCAL
    values = {"kj": facts.kj, "kcal": facts.kcal, "expected_kj": round(expected, 1)}
    ok = abs(facts.kj - expected) <= expected * KJ_TOLERANCE
    message = (
        f"{fmt(facts.kj)} кДж відповідає {fmt(facts.kcal)} ккал (очікувано "
        f"{fmt(round(expected))} кДж)."
        if ok
        else f"{fmt(facts.kj)} кДж не відповідає {fmt(facts.kcal)} ккал (очікувано "
        f"{fmt(round(expected))} кДж ±3 %) — перевірте таблицю."
    )
    status = "pass" if ok else "needs_review"
    return [
        finding("NUT-KJ", "energy", status, message, facts.photo_index, facts.raw["energy"], values)
    ]


def check_subsets(facts: NutritionFacts) -> list[Finding]:
    """NUT-SUBSETS: sugars ≤ carbs, saturates ≤ fat ("з них")."""
    findings = []
    for part, whole in (("sugars", "carbs"), ("saturates", "fat")):
        a, b = facts.amounts[part], facts.amounts[whole]
        if a is None or b is None:
            continue  # LABEL-MISSING reports it
        part_min, whole_max = _bounds(a)[0], _bounds(b)[1]
        values = {part: a.value, whole: b.value}
        fragment = f"{facts.raw[part]} / {facts.raw[whole]}"
        name, whole_name = NUTRIENT_NAMES_UK[part], NUTRIENT_NAMES_UK[whole]
        if part_min <= whole_max:
            findings.append(
                finding(
                    "NUT-SUBSETS",
                    part,
                    "pass",
                    f"«{name.capitalize()}» не більше за «{whole_name}».",
                    facts.photo_index,
                    fragment,
                    values,
                )
            )
        else:
            findings.append(
                finding(
                    "NUT-SUBSETS",
                    part,
                    "needs_review",
                    f"«{name.capitalize()}» ({fmt(part_min)} г) більше за «{whole_name}» "
                    f"({fmt(whole_max)} г), а це їх частина — помилка етикетки або читання фото.",
                    facts.photo_index,
                    fragment,
                    values,
                )
            )
    return findings


def spec_tolerance(nutrient: str, recipe: float) -> float:
    """Allowed |label - recipe|: EU guidance on tolerances for nutrition labelling (2012),
    the recipe value taken as the reference. SPEC's start was ±20 % / ±2 g; the guidance is
    the same idea per nutrient (±2 g of salt would hide anything)."""
    if nutrient == "energy":
        return 0.2 * recipe
    if nutrient == "saturates":
        return 0.8 if recipe < 4 else 0.2 * recipe
    if nutrient == "salt":
        return 0.375 if recipe < 1.25 else 0.2 * recipe
    small = 1.5 if nutrient == "fat" else 2.0  # carbs, sugars, fibre, protein
    if recipe < 10:
        return small
    return 0.2 * recipe if recipe <= 40 else 8.0


def check_spec(facts: NutritionFacts, spec: ProductSpec | None) -> list[Finding]:
    """NUT-SPEC: label values vs the recipe's nutrition_per_100."""
    if spec is None or spec.nutrition_per_100 is None:
        return [
            finding(
                "NUT-SPEC",
                None,
                "not_checked",
                "Без поживної цінності в рецептурі не перевірити таблицю етикетки.",
            )
        ]
    if facts.per not in ("100g", "100ml"):
        return [
            finding(
                "NUT-SPEC",
                None,
                "needs_review",
                "Таблиця на етикетці не на 100 г / 100 мл — з рецептурою не порівняти.",
                facts.photo_index,
            )
        ]
    recipe = spec.nutrition_per_100.model_dump()
    label: dict[str, Amount | None] = dict(facts.amounts)
    label["energy"] = None if facts.kcal is None else Amount(facts.kcal, "eq")
    findings = []
    for nutrient in ("energy", *NUTRIENTS):
        expected = recipe["energy_kcal" if nutrient == "energy" else nutrient]
        amount = label[nutrient]
        if expected is None or amount is None:
            continue
        lo, hi = _bounds(amount)
        tol = spec_tolerance(nutrient, expected)
        if lo - tol <= expected <= hi + tol:
            continue
        unit = "ккал" if nutrient == "energy" else "г"
        shown = fmt(hi) if lo == hi else f"{fmt(lo)}–{fmt(hi)}"
        findings.append(
            finding(
                "NUT-SPEC",
                nutrient,
                "needs_review",
                f"«{NUTRIENT_NAMES_UK[nutrient].capitalize()}»: на етикетці {shown} {unit}, у "
                f"рецептурі {fmt(expected)} {unit} (допуск ±{fmt(tol)} {unit}).",
                facts.photo_index,
                facts.raw[nutrient],
                {"label": amount.value, "recipe": expected},
                tol,
            )
        )
    if findings:
        return findings
    return [
        finding(
            "NUT-SPEC",
            None,
            "pass",
            "Значення таблиці відповідають рецептурі в межах допусків.",
            facts.photo_index,
        )
    ]


def check_nutrition(extraction: LabelExtraction, spec: ProductSpec | None) -> list[Finding]:
    facts = read_nutrition(extraction.nutrition)
    if facts is None:
        return []  # no table: LABEL-MISSING
    return [*check_energy(facts), *check_kj(facts), *check_subsets(facts), *check_spec(facts, spec)]
