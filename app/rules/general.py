"""General rules: IMG-QUALITY, LABEL-MISSING, LABEL-TRUNCATED, SIDE-FRONT-MISSING, NUT-PER.

They say what the photos do not let us check; nothing here turns an unknown into pass.
"""

from app.parsing import TRUNCATION_MARKERS, Ingredients
from app.rules.catalog import finding
from app.rules.nutrition import NUTRIENT_NAMES_UK, NutritionFacts
from app.schemas import Finding, LabelExtraction

QUALITY_UK = {
    "blurry": "розмите",
    "glare": "з відблиском",
    "cropped": "обрізане",
    "not_a_label": "не схоже на етикетку",
}


def check_image_quality(extraction: LabelExtraction) -> list[Finding]:
    """IMG-QUALITY: a photo the model flagged -> needs_review. The model's "ok" is only a
    hint (B1b: "ok" on cropped photos), so a good photo gives no finding, not a pass."""
    return [
        finding(
            "IMG-QUALITY",
            f"photo_{photo.index}",
            "needs_review",
            f"Фото {photo.index + 1} {QUALITY_UK[photo.quality]} — перефотографуйте фото "
            f"{photo.index + 1}.",
            photo.index,
            photo.note,
        )
        for photo in extraction.photos or []
        if photo.quality is not None and photo.quality != "ok"
    ]


def _readable(text: str | None) -> bool:
    if not text:
        return False
    rest = text
    for marker in TRUNCATION_MARKERS:
        rest = rest.replace(marker, "")
    return any(c.isalnum() for c in rest)


ENERGY_BOTH_UK = "енергетична цінність (потрібні і кДж, і ккал)"


def check_label_missing(extraction: LabelExtraction, facts: NutritionFacts | None) -> list[Finding]:
    """LABEL-MISSING: the ingredient list and the nutrition table are on the photos and the
    table's mandatory fields are readable."""
    item = extraction.ingredients_marked
    if item and _readable(item.text):
        ingredients = finding(
            "LABEL-MISSING", "ingredients", "pass", "Склад є на фото.", item.photo_index
        )
    else:
        ingredients = finding(
            "LABEL-MISSING",
            "ingredients",
            "needs_review",
            "Складу на фото не знайдено — сфотографуйте склад.",
        )
    if facts is None:
        table = finding(
            "LABEL-MISSING",
            "nutrition",
            "needs_review",
            "Таблиці поживної цінності на фото не знайдено — сфотографуйте таблицю.",
        )
    elif unreadable := facts.unreadable():
        names = ", ".join(
            ENERGY_BOTH_UK if n == "energy" else NUTRIENT_NAMES_UK[n] for n in unreadable
        )
        table = finding(
            "LABEL-MISSING",
            "nutrition",
            "needs_review",
            f"У таблиці не прочитано обов'язкові показники: {names} — перевірте на фото.",
            facts.photo_index,
            values={n: facts.raw[n] for n in unreadable},
        )
    else:
        table = finding(
            "LABEL-MISSING",
            "nutrition",
            "pass",
            "Таблиця поживної цінності є, обов'язкові показники прочитано.",
            facts.photo_index,
        )
    return [ingredients, table]


def check_truncated(extraction: LabelExtraction, ing: Ingredients) -> list[Finding]:
    """LABEL-TRUNCATED: a "[…]" in the ingredient list."""
    item = extraction.ingredients_marked
    if not ing.mentions or item is None:
        return []  # no list: LABEL-MISSING
    if ing.truncated:
        return [
            finding(
                "LABEL-TRUNCATED",
                "ingredients",
                "needs_review",
                "Склад прочитано не повністю (обрізано або нечитабельно) — перефотографуйте.",
                item.photo_index,
                next(m.text for m in ing.mentions if any(t in m.text for t in TRUNCATION_MARKERS)),
            )
        ]
    return [
        finding(
            "LABEL-TRUNCATED",
            "ingredients",
            "pass",
            "Склад прочитано без пропусків.",
            item.photo_index,
        )
    ]


def check_front(extraction: LabelExtraction) -> list[Finding]:
    """SIDE-FRONT-MISSING: claims are usually on the front; without it they are not checked."""
    if any(photo.side == "front" for photo in extraction.photos or []):
        # The front always has at least the product name: no text outside the ingredients and
        # the table means the model lost it (a dropped or renamed key), not that there are no
        # claims (RR2 #1).
        if not any(_readable(item.text) for item in extraction.other_text or []):
            return [
                finding(
                    "SIDE-FRONT-MISSING",
                    None,
                    "not_checked",
                    "Текст упаковки поза складом і таблицею не розпізнано — твердження "
                    "не перевірено.",
                )
            ]
        return [finding("SIDE-FRONT-MISSING", None, "pass", "Є фото лицьового боку.")]
    return [
        finding(
            "SIDE-FRONT-MISSING",
            None,
            "not_checked",
            "Немає фото лицьового боку — твердження з нього не перевірено; сфотографуйте фронт.",
        )
    ]


def check_per(facts: NutritionFacts | None) -> list[Finding]:
    """NUT-PER: claim thresholds are per 100 g / 100 ml."""
    if facts is None:
        return []
    if facts.per in ("100g", "100ml"):
        per = "100 г" if facts.per == "100g" else "100 мл"
        return [
            finding("NUT-PER", None, "pass", f"Таблиця на {per}.", facts.photo_index, facts.per)
        ]
    what = {"portion": "лише на порцію", "prepared": "у приготованому вигляді"}.get(
        facts.per or "", "без зрозумілої основи (на 100 г / 100 мл?)"
    )
    return [
        finding(
            "NUT-PER",
            None,
            "needs_review",
            f"Таблиця {what} — пороги тверджень (на 100 г / 100 мл) автоматично не перевірити.",
            facts.photo_index,
            facts.per,
        )
    ]
