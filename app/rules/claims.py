"""Nutrition claims: found by regexes in the label's other text (uk + en), checked against
the conditions of MoH Order 1145 (= Reg. 1924/2006 annex), per 100 g / 100 ml.

The code finds the claims, not the model. Comparative, health and unregulated wording ->
CLAIM-UNVERIFIABLE (needs_review): no automatic verdict.

Thresholds: Reg. 1924/2006 annex, which Order 1145 reproduces; the sugar thresholds were
confirmed against Ukrainian sources. Decisions (B2c, docs/NOTES.md): "без цукру" is
"not more than" 0.5 g; lactose is an added sugar, maltodextrin is disputed (needs_review);
satfat_low counts saturates only (no trans fats in the table), so a margin < 0.1 g to the
limit is needs_review.
"""

import re
from dataclasses import dataclass

from app.parsing import Amount, Ingredients
from app.rules.catalog import RULES, finding
from app.rules.nutrition import NutritionFacts, at_least, fmt
from app.schemas import Finding, LabelExtraction, ProductSpec, Status, TextItem

_END = r"(?!\w)"
# "без цукру та жиру", "без солі, цукру": other nutrients listed before this one (RR1 #3)
_LISTED = r"(?:\w+(?:,| та| і| й| and|,? or) )*"

CLAIM_PATTERNS: dict[str, list[str]] = {
    "sugar_free": [
        rf"без {_LISTED}цукр\w*",
        rf"не містить {_LISTED}цукр\w*",
        r"цукр\w* не містить",
        r"0 ?(?:%|г|g) цукр\w*",
        rf"(?:{_LISTED}sugar|zero sugars?) free",
        rf"(?:no|zero) {_LISTED}sugars?{_END}(?! added)",
        r"0 ?(?:%|g) (?:of )?sugars?",
    ],
    "low_sugar": [r"(?<!дуже )низьк\w* вміст\w* цукр\w*", r"low (?:in )?sugars?"],
    "no_added_sugar": [
        rf"без {_LISTED}(?:додан\w*|додаванн\w*) цукр\w*",
        r"не містить додан\w* цукр\w*",
        r"no added sugars?",
        r"no sugars? added",
        r"without added sugars?",
    ],
    "protein_source": [r"джерел\w* (?:білк\w*|протеїн\w*)", r"(?:good )?source of protein"],
    "protein_high": [
        r"(?:висок\w* вміст\w*|багат\w* на) (?:білк\w*|протеїн\w*)",
        r"high (?:in )?protein",
        r"rich in protein",
    ],
    "fat_low": [r"(?<!дуже )низьк\w* вміст\w* жир\w*", r"low (?:in )?fat"],
    "fat_free": [
        rf"без {_LISTED}жир\w*",
        r"знежирен\w*",
        rf"не містить {_LISTED}жир\w*",
        r"жир\w* не містить",
        r"0 ?(?:%|г|g) жир\w*",
        rf"(?:{_LISTED}fat|zero fat) free",
        r"(?:no|zero) fat" + _END,
        r"0 ?(?:%|g) (?:of )?fat",
    ],
    "satfat_low": [r"низьк\w* вміст\w* насичен\w* жир\w*", r"low (?:in )?saturated fat"],
    "fibre_source": [
        r"джерел\w* (?:клітковин\w*|харчов\w* волок\w*)",
        r"source of fib(?:re|er)",
    ],
    "fibre_high": [
        r"(?:висок\w* вміст\w*|багат\w* на) (?:клітковин\w*|харчов\w* волок\w*)",
        r"high (?:in )?fib(?:re|er)",
        r"rich in fib(?:re|er)",
    ],
    "salt_low": [
        r"(?<!дуже )низьк\w* вміст\w* (?:сол\w*|натрі\w*)",
        r"(?<!very )low (?:in )?(?:salt|sodium)",
    ],
    "salt_very_low": [
        r"дуже низьк\w* вміст\w* (?:сол\w*|натрі\w*)",
        r"very low (?:in )?(?:salt|sodium)",
    ],
    "energy_low": [
        r"низькокалорійн\w*",
        r"низьк\w* (?:калорійн\w*|енергетичн\w* цінн\w*)",
        r"low (?:calorie|energy|kcal)\w*",
    ],
}

# kind (the finding's target) -> patterns. Not judged automatically.
UNVERIFIABLE_PATTERNS: dict[str, list[str]] = {
    "comparative": [
        r"на \d+(?:[.,]\d+)? ?% менше",
        r"менше (?:цукр|жир|сол|калор)\w*",
        r"(?:зменшен|знижен)\w* (?:вміст\w*|калорійн\w*)",
        rf"(?:легк\w*|лайт|light|lite){_END}",
        r"reduced \w+",
        r"less (?:sugar|fat|salt)",
    ],
    "health": [
        r"корисн\w*",
        r"здоров\w*",
        r"імунітет\w*",
        r"зміцн\w*",
        r"сприя\w*",
        r"підтриму\w* (?:імун|здоров|серц|травл|енерг)\w*",
        r"для (?:серця|кісток|травлення|імунітету)",
        r"пробіотик\w*",
        r"healthy",
        r"immun\w*",
    ],
    "unregulated": [
        r"натуральн\w*",
        r"природн\w*",
        r"без (?:консервант|барвник|гмо|ароматизатор|підсилювач)\w*",
        r"органічн\w*",
        rf"(?:біо|еко|bio|eco){_END}",
        r"фермерськ\w*",
        r"домашн\w*",
        r"веган\w*",
        r"без (?:лактоз|глютен)\w*",
        r"natural\w*",
        r"organic",
        r"vegan",
        r"(?:gluten|lactose) free",
        r"no (?:preservatives|artificial)\w*",
    ],
    # nutrition claims outside the 13 automated ones
    "nutrition_other": [
        rf"без {_LISTED}сол\w*",
        rf"не містить {_LISTED}сол\w*",
        r"нежирн\w*",  # not a term of Order 1145: low fat or fat free? (RR1 #3)
        r"salt free",
        r"без калорі\w*",
        r"(?:джерел\w*|багат\w* на) (?:вітамін|кальці|залі?з|омега|мінерал|енергі)\w*",
        r"source of (?:vitamin|calcium|iron|omega)\w*",
    ],
}
UNVERIFIABLE_UK = {
    "comparative": "порівняльне твердження (потрібен продукт для порівняння)",
    "health": "твердження про користь для здоров'я (лише з дозволеного переліку)",
    "unregulated": "нерегульоване або окремо регульоване формулювання",
    "nutrition_other": "твердження про поживну цінність поза автоматичною перевіркою",
}

# The statement Order 1145 requires next to "без доданого цукру" when sugars are present.
NATURAL_SUGARS_RE = re.compile(
    r"(?<!\w)(?:містить природн\w* цукр\w*|contains naturally occurring sugars?)", re.I
)
# Mono-/disaccharides and foods used for sweetening; lactose counts as an added sugar.
ADDED_SUGAR_RE = re.compile(
    r"(?<!\w)(?:"
    rf"цукор|цукр(?:у|ом|і|и|ів)?{_END}|цукров\w*|мед(?:у|ом|ов\w*)?{_END}|сироп\w*|паток\w*|"
    r"мел[яа]с\w*|декстроз\w*|глюкоз\w*|фруктоз\w*|сахароз\w*|мальтоз\w*|лактоз\w*|"
    r"галактоз\w*|трегалоз\w*|інвертн\w*|"
    # fruit juice concentrates in any word order, with the fruit in between
    r"(?:концентрован|концентрат)\w* (?:\w+ ){0,2}с[оі]к\w*|"
    r"с[оі]к\w* (?:\w+ ){0,2}концентрован\w*|"
    r"солодов\w* екстракт\w*|екстракт\w* солод\w*|"
    rf"sugars?{_END}|honey|syrup\w*|molasses|dextrose|glucose|fructose|sucrose|maltose|lactose|"
    r"galactose|trehalose|malt extract|juice concentrate|concentrated \w+ juice"
    r")",
    re.I,
)
# Not a mono-/disaccharide, but sweetens and is argued about: never a silent pass.
DISPUTED_SUGAR_RE = re.compile(r"(?<!\w)(?:мальтодекстрин\w*|maltodextrin\w*)", re.I)


def _compile(patterns: list[str]) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w)(?:{'|'.join(patterns)})", re.I)


_CLAIM_RES = {cid: _compile(p) for cid, p in CLAIM_PATTERNS.items()}
_UNVERIFIABLE_RES = {kind: _compile(p) for kind, p in UNVERIFIABLE_PATTERNS.items()}


def normalize(text: str) -> str:
    """Hyphens and dashes to spaces, whitespace collapsed: "sugar-free" == "sugar free"."""
    return " ".join(re.sub(r"[-‐‑–—_]+", " ", text).split())


@dataclass
class _Found:
    items: list[TextItem]

    @property
    def fragment(self) -> str:
        return "; ".join(dict.fromkeys(i.text for i in self.items if i.text))

    @property
    def photo_index(self) -> int | None:
        return self.items[0].photo_index


def find_claims(extraction: LabelExtraction) -> tuple[dict[str, _Found], dict[str, _Found]]:
    """Claims and unverifiable wording in other_text -> ({claim_id: found}, {kind: found})."""
    claims: dict[str, _Found] = {}
    unverifiable: dict[str, _Found] = {}
    for item in extraction.other_text or []:
        if not item.text:
            continue
        text = normalize(item.text)
        for claim_id, regex in _CLAIM_RES.items():
            if regex.search(text):
                claims.setdefault(claim_id, _Found([])).items.append(item)
        rest = NATURAL_SUGARS_RE.sub(" ", text)  # the required statement is not a claim
        for kind, regex in _UNVERIFIABLE_RES.items():
            if regex.search(rest):
                unverifiable.setdefault(kind, _Found([])).items.append(item)
    order = list(CLAIM_PATTERNS)
    return dict(sorted(claims.items(), key=lambda kv: order.index(kv[0]))), unverifiable


# --- evaluation ------------------------------------------------------------------------------

# claim -> (nutrient, limit solid, limit liquid): the amount per 100 g / 100 ml is at most
MAX_LIMITS: dict[str, tuple[str, float, float]] = {
    "sugar_free": ("sugars", 0.5, 0.5),
    "low_sugar": ("sugars", 5.0, 2.5),
    "fat_low": ("fat", 3.0, 1.5),
    "fat_free": ("fat", 0.5, 0.5),
    "salt_low": ("salt", 0.3, 0.3),  # sodium <= 0.12 g
    "salt_very_low": ("salt", 0.1, 0.1),  # sodium <= 0.04 g
    "energy_low": ("energy", 40.0, 20.0),  # kcal
}
SATFAT_LIMITS = (1.5, 0.75)  # g, solid / liquid
SATFAT_MAX_ENERGY_PCT = 10.0
# The law limits saturates + trans fats; the table has no trans fats, so a pass needs
# this much room under the limit (g), otherwise needs_review.
SATFAT_MARGIN = 0.1
SATFAT_BASIS = "лише насичені жири: транс-жирів у таблиці немає, а поріг закону — на їх суму"
PROTEIN_MIN_ENERGY_PCT = {"protein_source": 12.0, "protein_high": 20.0}
FIBRE_MIN = {"fibre_source": (3.0, 1.5), "fibre_high": (6.0, 3.0)}  # g/100 g, g/100 kcal
SUGARS_FREE_LIMIT = 0.5  # sugars this low need no "містить природні цукри"

NUTRIENT_GEN_UK = {
    "sugars": "цукри",
    "fat": "жири",
    "saturates": "насичені жири",
    "salt": "сіль",
    "protein": "білки",
    "fibre": "клітковина",
    "energy": "енергетична цінність",
}


@dataclass(frozen=True)
class _Result:
    status: Status
    message: str
    values: dict[str, float | str | None] | None = None
    threshold: float | str | None = None


def product_form(facts: NutritionFacts | None, spec: ProductSpec | None) -> str | None:
    """solid | liquid: from the recipe, else from the table's basis; None if unknown."""
    if spec and spec.form:
        return spec.form
    if facts and facts.per == "100g":
        return "solid"
    if facts and facts.per == "100ml":
        return "liquid"
    return None


def _range(amount: Amount | None) -> tuple[float, float] | None:
    """Where the true amount is; None for unknown or "сліди" (no number to compare)."""
    if amount is None or amount.qualifier == "trace":
        return None
    return (0.0, amount.value) if amount.qualifier == "lt" else (amount.value, amount.value)


def _shown(amount: Amount) -> str:
    return ("<" if amount.qualifier == "lt" else "") + fmt(amount.value)


def _amount(facts: NutritionFacts, nutrient: str) -> Amount | None:
    if nutrient == "energy":
        return None if facts.kcal is None else Amount(facts.kcal, "eq")
    return facts.amounts[nutrient]


def _check_max(
    title: str, facts: NutritionFacts, nutrient: str, limit: float, basis: str
) -> _Result:
    amount = _amount(facts, nutrient)
    bounds = _range(amount)
    name = NUTRIENT_GEN_UK[nutrient]
    unit = "ккал" if nutrient == "energy" else "г"
    if bounds is None:
        why = "«сліди» без числа" if amount else "значення не прочитано"
        return _Result(
            "needs_review",
            f"Твердження «{title}»: {name} — {why}; поріг ≤ {fmt(limit)} {unit} на {basis} — "
            "перевірте таблицю.",
            {nutrient: None},
            limit,
        )
    lo, hi = bounds
    values = {nutrient: amount.value}
    head = (
        f"Твердження «{title}»: {name} {_shown(amount)} {unit} на {basis}, "
        f"поріг ≤ {fmt(limit)} {unit}"
    )
    if hi <= limit:
        return _Result("pass", f"{head} — виконано.", values, limit)
    if lo > limit:
        return _Result("violation", f"{head} — поріг перевищено.", values, limit)
    return _Result("needs_review", f"{head} — точне значення невідоме.", values, limit)


def _check_protein(title: str, facts: NutritionFacts, minimum: float) -> _Result:
    bounds = _range(facts.amounts["protein"])
    if bounds is None or not facts.kcal:
        return _Result(
            "needs_review",
            f"Твердження «{title}»: не прочитано білки або ккал — частку енергії з білка "
            f"(поріг ≥ {fmt(minimum)} %) не порахувати.",
            threshold=minimum,
        )
    lo, hi = (b * 4 * 100 / facts.kcal for b in bounds)
    values = {
        "protein": facts.amounts["protein"].value,
        "kcal": facts.kcal,
        "energy_pct": round(hi, 1),
    }
    head = (
        f"Твердження «{title}»: білок дає {fmt(round(hi, 1))} % енергії "
        f"({_shown(facts.amounts['protein'])} г × 4 ккал / {fmt(facts.kcal)} ккал), "
        f"поріг ≥ {fmt(minimum)} %"
    )
    if at_least(lo, minimum):
        return _Result("pass", f"{head} — виконано.", values, minimum)
    if not at_least(hi, minimum):
        return _Result("violation", f"{head} — не виконано.", values, minimum)
    return _Result("needs_review", f"{head} — точне значення невідоме.", values, minimum)


def _check_fibre(title: str, facts: NutritionFacts, per_100g: float, per_100kcal: float) -> _Result:
    bounds = _range(facts.amounts["fibre"])
    if bounds is None:
        return _Result(
            "needs_review",
            f"Твердження «{title}»: клітковину не прочитано (поріг ≥ {fmt(per_100g)} г / 100 г "
            f"або ≥ {fmt(per_100kcal)} г / 100 ккал) — перевірте таблицю.",
            threshold=per_100g,
        )
    lo, hi = bounds
    fibre = facts.amounts["fibre"]
    values: dict[str, float | str | None] = {"fibre": fibre.value, "kcal": facts.kcal}
    rule = f"поріг ≥ {fmt(per_100g)} г / 100 г або ≥ {fmt(per_100kcal)} г / 100 ккал"
    per_kcal = None
    if facts.kcal:
        per_kcal = (lo * 100 / facts.kcal, hi * 100 / facts.kcal)
        values["fibre_per_100kcal"] = round(per_kcal[1], 2)
    shown = f"клітковина {_shown(fibre)} г"
    if per_kcal:
        shown += f" ({fmt(round(per_kcal[1], 2))} г / 100 ккал)"
    head = f"Твердження «{title}»: {shown}, {rule}"
    if at_least(lo, per_100g) or (per_kcal and at_least(per_kcal[0], per_100kcal)):
        return _Result("pass", f"{head} — виконано.", values, per_100g)
    fails_kcal = per_kcal is not None and not at_least(per_kcal[1], per_100kcal)
    if not at_least(hi, per_100g) and fails_kcal:
        return _Result("violation", f"{head} — не виконано.", values, per_100g)
    return _Result(
        "needs_review",
        f"{head} — не визначити (немає ккал або точного значення).",
        values,
        per_100g,
    )


def _check_satfat(title: str, facts: NutritionFacts, form: str) -> _Result:
    limit = SATFAT_LIMITS[0] if form == "solid" else SATFAT_LIMITS[1]
    bounds = _range(facts.amounts["saturates"])
    if bounds is None or not facts.kcal:
        return _Result(
            "needs_review",
            f"Твердження «{title}»: не прочитано насичені жири або ккал (поріг ≤ {fmt(limit)} г і "
            f"≤ {fmt(SATFAT_MAX_ENERGY_PCT)} % енергії) — перевірте таблицю.",
            threshold=limit,
        )
    lo, hi = bounds
    pct_lo, pct_hi = lo * 9 * 100 / facts.kcal, hi * 9 * 100 / facts.kcal
    sat = facts.amounts["saturates"]
    values = {
        "saturates": sat.value,
        "kcal": facts.kcal,
        "energy_pct": round(pct_hi, 1),
        "margin_g": round(limit - hi, 3),
        "basis": SATFAT_BASIS,
    }
    head = (
        f"Твердження «{title}»: насичені жири {_shown(sat)} г ({fmt(round(pct_hi, 1))} % енергії), "
        f"поріг ≤ {fmt(limit)} г і ≤ {fmt(SATFAT_MAX_ENERGY_PCT)} % енергії"
    )
    if lo > limit or not at_least(SATFAT_MAX_ENERGY_PCT, pct_lo):
        return _Result("violation", f"{head} — не виконано.", values, limit)
    if hi <= limit and at_least(SATFAT_MAX_ENERGY_PCT, pct_hi):
        if at_least(limit - hi, SATFAT_MARGIN):
            return _Result("pass", f"{head} — виконано.", values, limit)
        return _Result(
            "needs_review",
            f"{head} — запас до порогу менше {fmt(SATFAT_MARGIN)} г, а поріг закону — на суму "
            "насичених і транс-жирів, яких у таблиці немає; перевірте за рецептурою.",
            values,
            limit,
        )
    return _Result("needs_review", f"{head} — точне значення невідоме.", values, limit)


def _check_no_added_sugar(
    title: str, facts: NutritionFacts | None, ing: Ingredients, extraction: LabelExtraction
) -> _Result:
    if not ing.mentions:
        return _Result(
            "needs_review",
            f"Твердження «{title}»: склад не прочитано — не перевірити, чи немає доданих цукрів.",
        )
    added = [m.text for m in ing.mentions if ADDED_SUGAR_RE.search(m.text)]
    if added:
        return _Result(
            "violation",
            f"Твердження «{title}», але у складі є цукри або підсолоджувальні продукти: "
            f"{'; '.join(added)}.",
            {"ingredients": "; ".join(added)},
        )
    result = _no_added_sugar_rest(title, facts, ing, extraction)
    disputed = [m.text for m in ing.mentions if DISPUTED_SUGAR_RE.search(m.text)]
    if disputed and result.status != "violation":
        rest = "" if result.status == "pass" else f" Крім того: {result.message}"
        return _Result(
            "needs_review",
            f"Твердження «{title}»: у складі спірний підсолоджувальний інгредієнт "
            f"({'; '.join(disputed)}) — оцініть вручну.{rest}",
            {"ingredients": "; ".join(disputed)},
        )
    return result


def _no_added_sugar_rest(
    title: str, facts: NutritionFacts | None, ing: Ingredients, extraction: LabelExtraction
) -> _Result:
    """After the definite added sugars: truncation and the natural sugars statement."""
    if ing.truncated:
        return _Result(
            "needs_review",
            f"Твердження «{title}»: склад прочитано не повністю — доданий цукор міг бути в "
            "пропущеній частині.",
        )
    statement = any(
        item.text and NATURAL_SUGARS_RE.search(normalize(item.text))
        for item in extraction.other_text or []
    )
    if statement:
        return _Result(
            "pass",
            f"Твердження «{title}»: доданих цукрів у складі немає, напис «містить "
            "природні цукри» є.",
        )
    bounds = _range(facts.amounts["sugars"]) if facts else None
    if bounds is None:
        return _Result(
            "needs_review",
            f"Твердження «{title}»: цукри в таблиці не прочитано — не перевірити, чи потрібен "
            "напис «містить природні цукри».",
        )
    lo, hi = bounds
    sugars = facts.amounts["sugars"]
    values = {"sugars": sugars.value}
    if hi <= SUGARS_FREE_LIMIT:
        return _Result(
            "pass",
            f"Твердження «{title}»: доданих цукрів у складі немає, цукри {_shown(sugars)} г.",
            values,
        )
    if lo > SUGARS_FREE_LIMIT:
        return _Result(
            "violation",
            f"Твердження «{title}»: цукри {_shown(sugars)} г, а напису «містить природні цукри» "
            "немає.",
            values,
        )
    return _Result(
        "needs_review",
        f"Твердження «{title}»: цукри {_shown(sugars)} г — не визначити, чи потрібен напис "
        "«містить природні цукри».",
        values,
    )


def evaluate_claim(
    claim_id: str,
    facts: NutritionFacts | None,
    form: str | None,
    ing: Ingredients,
    extraction: LabelExtraction,
) -> _Result:
    title = RULES[claim_id].title.removeprefix("Твердження «").removesuffix("»")
    if claim_id == "no_added_sugar":
        return _check_no_added_sugar(title, facts, ing, extraction)
    if facts is None:
        return _Result(
            "needs_review",
            f"Твердження «{title}» є, а таблиці поживної цінності немає — сфотографуйте таблицю.",
        )
    if facts.per not in ("100g", "100ml"):
        return _Result(
            "needs_review",
            f"Твердження «{title}»: таблиця не на 100 г / 100 мл — поріг не перевірити (NUT-PER).",
        )
    basis = "100 г" if facts.per == "100g" else "100 мл"
    if claim_id in PROTEIN_MIN_ENERGY_PCT:
        return _check_protein(title, facts, PROTEIN_MIN_ENERGY_PCT[claim_id])
    if claim_id in FIBRE_MIN:
        return _check_fibre(title, facts, *FIBRE_MIN[claim_id])
    needs_form = claim_id == "satfat_low" or (
        claim_id in MAX_LIMITS and MAX_LIMITS[claim_id][1] != MAX_LIMITS[claim_id][2]
    )
    if needs_form and form is None:
        return _Result(
            "needs_review",
            f"Твердження «{title}»: не визначено, тверде це чи рідке (поріг різний) — "
            "вкажіть form у рецептурі.",
        )
    if claim_id == "satfat_low":
        return _check_satfat(title, facts, form)
    nutrient, solid, liquid = MAX_LIMITS[claim_id]
    return _check_max(title, facts, nutrient, solid if form != "liquid" else liquid, basis)


def check_claims(
    extraction: LabelExtraction,
    spec: ProductSpec | None,
    facts: NutritionFacts | None,
    ing: Ingredients,
) -> list[Finding]:
    claims, unverifiable = find_claims(extraction)
    form = product_form(facts, spec)
    findings = []
    for claim_id, found in claims.items():
        r = evaluate_claim(claim_id, facts, form, ing, extraction)
        findings.append(
            finding(
                claim_id,
                claim_id,
                r.status,
                r.message,
                found.photo_index,
                found.fragment,
                r.values,
                r.threshold,
            )
        )
    for kind, found in unverifiable.items():
        findings.append(
            finding(
                "CLAIM-UNVERIFIABLE",
                kind,
                "needs_review",
                f"«{found.fragment}» — {UNVERIFIABLE_UK[kind]}: автоматично не перевіряється, "
                "оцініть вручну.",
                found.photo_index,
                found.fragment,
            )
        )
    return findings
