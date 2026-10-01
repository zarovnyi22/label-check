"""Allergen rules: ALG-EMPH, ALG-SPEC-MISSING, ALG-SPEC-EXTRA, ALG-MAY-CONTAIN.

Pure functions over the extraction (transcription) and the optional recipe. One finding per
allergen category (`target`), however many times it is mentioned. Only the ingredient list
counts as the composition: parse_ingredients cuts off storage/producer text (`tail`), and
"may contain" allergens need no emphasis.
"""

import re
from dataclasses import dataclass
from typing import get_args

from app.parsing import TRUNCATION_MARKERS, Ingredients, Mention, parse_ingredients
from app.rules.allergen_dict import (
    CATEGORY_NAMES_UK,
    EXCLUSION_PATTERNS,
    GLUTEN_RE,
    PATTERNS,
    SUBTYPE_PATTERNS,
)
from app.rules.catalog import finding
from app.schemas import AllergenCategory, Finding, LabelExtraction, ProductSpec, Status

CATEGORIES: tuple[AllergenCategory, ...] = get_args(AllergenCategory)
_MAY_CONTAIN_RE = re.compile(r"(?:може\s+(?:містити|вміщувати)|may\s+contain)[^.]*", re.I)


@dataclass(frozen=True)
class AllergenHit:
    category: AllergenCategory
    start: int  # [start, end) in the searched text
    end: int
    term: str


def find_allergens(text: str | None) -> list[AllergenHit]:
    """Dictionary terms in `text`, minus the words masked by an exclusion phrase."""
    if not text:
        return []
    masked = [m.span("x") for p in EXCLUSION_PATTERNS for m in p.finditer(text)]
    hits = [
        AllergenHit(category, m.start(), m.end(), m[0])
        for category, pattern in PATTERNS.items()
        for m in pattern.finditer(text)
        if not any(s < m.end() and m.start() < e for s, e in masked)
    ]
    return sorted(hits, key=lambda h: (h.start, CATEGORIES.index(h.category)))


def _name(category: AllergenCategory) -> str:
    return f"«{CATEGORY_NAMES_UK[category]}» ({category})"


@dataclass(frozen=True)
class _LabelAllergen:
    mention: Mention
    hit: AllergenHit
    emphasized: bool


def _label_allergens(ing: Ingredients) -> dict[AllergenCategory, list[_LabelAllergen]]:
    """Allergens of the ingredient list by category, with whether each is emphasized.

    A mention also counts as emphasized when a nested mention right after it names the same
    allergen emphasized: "сироватковий пермеат (з **молока**)" is the usual compliant form.
    """
    hits = [find_allergens(m.text) for m in ing.mentions]
    found: dict[AllergenCategory, list[_LabelAllergen]] = {}
    for i, (mention, mention_hits) in enumerate(zip(ing.mentions, hits, strict=True)):
        for hit in mention_hits:
            emphasized = mention.is_emphasized(hit.start, hit.end) or _clarified(
                ing.mentions, hits, i, hit.category
            )
            found.setdefault(hit.category, []).append(_LabelAllergen(mention, hit, emphasized))
    return {c: found[c] for c in CATEGORIES if c in found}


def _clarified(
    mentions: tuple[Mention, ...],
    hits: list[list[AllergenHit]],
    i: int,
    category: AllergenCategory,
) -> bool:
    j = i + 1
    while j < len(mentions) and mentions[j].depth > mentions[i].depth:
        if any(
            h.category == category and mentions[j].is_emphasized(h.start, h.end) for h in hits[j]
        ):
            return True
        j += 1
    return False


def _fragments(items: list[_LabelAllergen]) -> str:
    return "; ".join(dict.fromkeys(item.mention.text for item in items))


def _named(items: list[_LabelAllergen]) -> list[_LabelAllergen]:
    """Without "глютен": it is not the cereal's name (SPEC §2)."""
    return [item for item in items if not GLUTEN_RE.match(item.hit.term)]


def recipe_allergens(spec: ProductSpec) -> dict[AllergenCategory, list[str]]:
    """Category -> recipe ingredient names: the declared allergens and the ones the
    dictionary finds in the name ("молоко сухе" without `allergens` is still milk, RR1 #4)."""
    recipe: dict[AllergenCategory, list[str]] = {}
    for ingredient in spec.ingredients:
        found = {h.category for h in find_allergens(ingredient.name)}
        for category in (c for c in CATEGORIES if c in found or c in ingredient.allergens):
            recipe.setdefault(category, []).append(ingredient.name)
    return recipe


def _subtypes(category: AllergenCategory, texts: list[str]) -> set[str]:
    patterns = SUBTYPE_PATTERNS.get(category, {})
    return {name for name, p in patterns.items() if any(p.search(t) for t in texts)}


def _no_recipe_ingredients(rule_id: str) -> Finding:
    return finding(
        rule_id,
        None,
        "not_checked",
        "У рецептурі немає інгредієнтів — алергени етикетки з рецептурою не звірити.",
    )


def check_emphasis(
    ing: Ingredients,
    found: dict[AllergenCategory, list[_LabelAllergen]],
    resolvable: bool | None,
    photo_index: int | None,
) -> list[Finding]:
    """ALG-EMPH. A missing ** is never a violation (B1b: the model misses bold type), only
    needs_review; ** or capitals on the allergen word -> pass."""
    if not ing.mentions:
        return []  # no ingredient list on the photos: LABEL-MISSING
    if not found:
        return [
            finding(
                "ALG-EMPH",
                None,
                "not_applicable",
                "У складі не знайдено алергенів зі словника — виділяти нічого.",
                photo_index,
            )
        ]
    findings = []
    for category, all_items in found.items():
        items = _named(all_items)
        if not items:
            findings.append(
                finding(
                    "ALG-EMPH",
                    category,
                    "needs_review",
                    f"У складі є лише «глютен» без назви злаку — для {_name(category)} "
                    "потрібно назвати злак (пшениця, жито, ячмінь, овес) і виділити його.",
                    photo_index,
                    _fragments(all_items),
                )
            )
            continue
        plain = [item for item in items if not item.emphasized]
        if not plain:
            findings.append(
                finding(
                    "ALG-EMPH",
                    category,
                    "pass",
                    f"Алерген {_name(category)} у складі виділено шрифтом.",
                    photo_index,
                    _fragments(items),
                )
            )
            continue
        message = (
            f"Алерген {_name(category)} у складі без виділення: модель не підтвердила "
            "виділення шрифтом — перевірте шрифт на фото."
        )
        if resolvable is not True:
            message += " Фото не дозволяє розрізнити шрифт — за потреби перефотографуйте склад."
        if ing.upper_is_body:
            message += " Увесь склад надруковано великими літерами — регістр не виділяє алерген."
        if ing.marks_are_body:
            message += " Майже весь склад розмічено однаково — це стиль тексту, не виділення."
        findings.append(
            finding("ALG-EMPH", category, "needs_review", message, photo_index, _fragments(plain))
        )
    return findings


def check_spec_missing(
    ing: Ingredients,
    found: dict[AllergenCategory, list[_LabelAllergen]],
    spec: ProductSpec | None,
    photo_index: int | None,
) -> list[Finding]:
    """ALG-SPEC-MISSING: every allergen of the recipe is in the label's ingredient list."""
    if spec is None:
        return [
            finding(
                "ALG-SPEC-MISSING",
                None,
                "not_checked",
                "Без рецептури не перевірити, чи всі алергени зазначено на етикетці.",
            )
        ]
    if not spec.ingredients:
        return [_no_recipe_ingredients("ALG-SPEC-MISSING")]
    recipe = recipe_allergens(spec)
    if not recipe:
        return [
            finding("ALG-SPEC-MISSING", None, "pass", "У рецептурі алергенів немає.", photo_index)
        ]
    findings = []
    for category in (c for c in CATEGORIES if c in recipe):
        sources = ", ".join(recipe[category])
        named = _named(found.get(category, []))
        missing = sorted(
            _subtypes(category, recipe[category])
            - _subtypes(category, [m.text for m in ing.mentions])
        )
        if category in found and not named:
            status: Status = "needs_review"
            message = (
                f"Алерген {_name(category)} є в рецептурі ({sources}), а на етикетці — лише "
                "«глютен» без назви злаку."
            )
            fragment = _fragments(found[category])
        elif named and missing:
            status = "needs_review"
            message = (
                f"Алерген {_name(category)}: у рецептурі {', '.join(missing)} ({sources}), а на "
                "етикетці названо інше — перевірте, чи зазначено саме цей злак/горіх."
            )
            fragment = _fragments(named)
        elif named:
            status = "pass"
            message = f"Алерген {_name(category)} з рецептури ({sources}) є у складі на етикетці."
            fragment = _fragments(named)
        elif not ing.mentions:
            status = "needs_review"
            message = (
                f"Алерген {_name(category)} є в рецептурі ({sources}), але склад на фото не "
                "прочитано — сфотографуйте склад."
            )
            fragment = None
        elif ing.truncated:
            status = "needs_review"
            message = (
                f"Алерген {_name(category)} є в рецептурі ({sources}) і не знайдений у "
                "прочитаній частині складу; склад прочитано не повністю — перевірте на фото."
            )
            fragment = None
        else:
            status = "violation"
            message = (
                f"Алерген {_name(category)} є в рецептурі ({sources}), але не зазначений у "
                "складі на етикетці."
            )
            fragment = None
        findings.append(
            finding("ALG-SPEC-MISSING", category, status, message, photo_index, fragment)
        )
    return findings


def check_spec_extra(
    ing: Ingredients,
    found: dict[AllergenCategory, list[_LabelAllergen]],
    spec: ProductSpec | None,
    photo_index: int | None,
) -> list[Finding]:
    """ALG-SPEC-EXTRA: an allergen on the label that the recipe does not have."""
    if spec is None:
        return [
            finding(
                "ALG-SPEC-EXTRA",
                None,
                "not_checked",
                "Без рецептури не перевірити, чи алергени етикетки відповідають рецептурі.",
            )
        ]
    if not spec.ingredients:
        return [_no_recipe_ingredients("ALG-SPEC-EXTRA")]
    if not ing.mentions:
        return []  # nothing read, nothing extra: LABEL-MISSING / ALG-SPEC-MISSING report it
    recipe = recipe_allergens(spec)
    extra = [c for c in found if c not in recipe]
    if not extra:
        return [
            finding(
                "ALG-SPEC-EXTRA",
                None,
                "pass",
                "Усі алергени складу етикетки є в рецептурі.",
                photo_index,
            )
        ]
    return [
        finding(
            "ALG-SPEC-EXTRA",
            category,
            "needs_review",
            f"Алерген {_name(category)} є у складі на етикетці, але його немає в рецептурі — "
            "уточніть рецептуру або етикетку.",
            photo_index,
            _fragments(found[category]),
        )
        for category in extra
    ]


def may_contain_text(
    extraction: LabelExtraction, ing: Ingredients, list_photo: int | None
) -> tuple[str | None, int | None]:
    """The "may contain" sentence: the model's field, else from the cut-off list tail."""
    item = extraction.may_contain_text
    if item and item.text:
        return item.text, item.photo_index
    # "[...]" would end the sentence at its first dot: one-character marker first
    tail = ing.tail.replace("*", "").replace("[...]", "[…]") if ing.tail else None
    m = _MAY_CONTAIN_RE.search(tail) if tail else None
    return (m[0].strip(), list_photo) if m else (None, None)


def check_may_contain(
    extraction: LabelExtraction, ing: Ingredients, spec: ProductSpec | None, list_photo: int | None
) -> list[Finding]:
    """ALG-MAY-CONTAIN: the label's "may contain" vs the recipe's may_contain."""
    if spec is None:
        return [
            finding(
                "ALG-MAY-CONTAIN",
                None,
                "not_checked",
                "Без рецептури не перевірити напис «може містити».",
            )
        ]
    text, photo_index = may_contain_text(extraction, ing, list_photo)
    label = {h.category for h in find_allergens(text)}
    recipe = set(spec.may_contain)
    if text and any(t in text for t in TRUNCATION_MARKERS):
        return [
            finding(
                "ALG-MAY-CONTAIN",
                None,
                "needs_review",
                "Напис «може містити» прочитано не повністю ([…]) — перевірте його на фото.",
                photo_index,
                text,
            )
        ]
    if label == recipe:
        message = (
            "Напис «може містити» відповідає рецептурі."
            if recipe
            else "«Може містити» немає ні на етикетці, ні в рецептурі."
        )
        return [finding("ALG-MAY-CONTAIN", None, "pass", message, photo_index, text)]
    findings = []
    for category in CATEGORIES:
        if category in label and category not in recipe:
            message = (
                f"{_name(category)} є в написі «може містити» на етикетці, але не в "
                "рецептурі (may_contain)."
            )
        elif category in recipe and category not in label:
            where = "у написі «може містити»" if text else "— напису «може містити» на фото немає"
            message = f"{_name(category)} є в рецептурі (may_contain), але не на етикетці {where}."
        else:
            continue
        findings.append(
            finding("ALG-MAY-CONTAIN", category, "needs_review", message, photo_index, text)
        )
    return findings


def check_allergens(extraction: LabelExtraction, spec: ProductSpec | None) -> list[Finding]:
    item = extraction.ingredients_marked
    ing = parse_ingredients(item.text if item else None)
    photo_index = item.photo_index if item else None
    found = _label_allergens(ing)
    return [
        *check_emphasis(ing, found, extraction.emphasis_resolvable, photo_index),
        *check_spec_missing(ing, found, spec, photo_index),
        *check_spec_extra(ing, found, spec, photo_index),
        *check_may_contain(extraction, ing, spec, photo_index),
    ]
