"""Data contracts (docs/SPEC.md §1): the recipe, what the model transcribes, findings, results.

LabelExtraction is transcription only: every field may be null, numbers stay strings as
printed and are parsed by app.parsing. An enum value the model invents becomes null
("unknown is not allowed"), never a guess.
"""

from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

# The 14 allergen groups of Law 2639-VIII / Reg. 1169/2011 Annex II.
AllergenCategory = Literal[
    "cereals",  # cereals containing gluten: wheat, rye, barley, oats, spelt, kamut
    "crustaceans",
    "eggs",
    "fish",
    "peanuts",
    "soybeans",
    "milk",
    "nuts",  # tree nuts: almond, hazelnut, walnut, cashew, pecan, Brazil, pistachio, macadamia
    "celery",
    "mustard",
    "sesame",
    "sulphites",
    "lupin",
    "molluscs",
]

Status = Literal["pass", "violation", "needs_review", "not_checked", "not_applicable"]
Verdict = Literal["fail", "needs_review", "incomplete", "pass"]

Side = Literal["front", "back", "side", "unknown"]
Quality = Literal["ok", "blurry", "glare", "cropped", "not_a_label"]
Per = Literal["100g", "100ml", "portion", "prepared"]


def _known_or(allowed: tuple[str, ...], fallback: str | None):
    """Before-validator: a value outside the enum (or the string "null") becomes `fallback`."""

    def coerce(value: Any) -> Any:
        if isinstance(value, str) and value.strip().lower() in allowed:
            return value.strip().lower()
        return fallback

    return BeforeValidator(coerce)


# --- input: the recipe (specification) ---------------------------------------------------


class SpecIngredient(BaseModel):
    # A typo ("alergens") must fail, not silently mean "no allergens" (a missed ALG-SPEC-MISSING).
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    allergens: list[AllergenCategory] = []


class SpecNutrition(BaseModel):
    """Recipe values per 100 g / 100 ml, as numbers (the recipe is typed, not photographed)."""

    model_config = ConfigDict(extra="forbid")

    energy_kcal: float | None = Field(default=None, ge=0)
    fat: float | None = Field(default=None, ge=0)
    saturates: float | None = Field(default=None, ge=0)
    carbs: float | None = Field(default=None, ge=0)
    sugars: float | None = Field(default=None, ge=0)
    fibre: float | None = Field(default=None, ge=0)
    protein: float | None = Field(default=None, ge=0)
    salt: float | None = Field(default=None, ge=0)


class ProductSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str | None = None
    form: Literal["solid", "liquid"] | None = None
    ingredients: list[SpecIngredient] = []
    may_contain: list[AllergenCategory] = []
    nutrition_per_100: SpecNutrition | None = None


# --- model output: transcription only ------------------------------------------------------


class Photo(BaseModel):
    index: int = Field(ge=0)
    side: Annotated[Side, _known_or(get_args(Side), "unknown")] = "unknown"
    # A hint only: the spike saw "ok" on cropped photos (docs/NOTES.md, B1b).
    quality: Annotated[Quality | None, _known_or(get_args(Quality), None)] = None
    note: str | None = None


class TextItem(BaseModel):
    """A verbatim text from one photo; "[…]" marks a cut-off or unreadable fragment."""

    text: str | None = None
    photo_index: int | None = Field(default=None, ge=0)


class Nutrition(BaseModel):
    # Values are strings as printed ("<0,5 г"); a bare number from the model is kept as text.
    model_config = ConfigDict(coerce_numbers_to_str=True)

    per: Annotated[Per | None, _known_or(get_args(Per), None)] = None
    portion_text: str | None = None
    energy: str | None = None
    fat: str | None = None
    saturates: str | None = None
    carbs: str | None = None
    sugars: str | None = None
    fibre: str | None = None
    protein: str | None = None
    salt: str | None = None
    photo_index: int | None = Field(default=None, ge=0)


class LabelExtraction(BaseModel):
    # Unknown keys from the model are dropped, not an error: a missing key is just null.
    photos: list[Photo] | None = None
    # Whether the photo lets anyone tell bold from regular at all; NOT whether there is
    # emphasis (that is the **…** markup in ingredients_marked).
    emphasis_resolvable: bool | None = None
    ingredients_marked: TextItem | None = None
    may_contain_text: TextItem | None = None
    nutrition: Nutrition | None = None
    other_text: list[TextItem] | None = None


# --- output: findings and the check result ---------------------------------------------------


class Evidence(BaseModel):
    photo_index: int | None = None
    fragment: str | None = None  # verbatim from the photo
    values: dict[str, float | str | None] | None = None  # numbers the code computed with
    threshold: float | str | None = None


class Finding(BaseModel):
    rule_id: str
    target: str | None = None  # allergen category, claim id, nutrient or null
    status: Status
    message: str  # written by the code, never by the model
    evidence: Evidence | None = None
    legal_ref: str


class CheckError(BaseModel):
    code: str
    message: str


class CheckOut(BaseModel):
    check_id: int
    status: Literal["done", "error"]
    verdict: Verdict | None  # null only for status=error: a failed check is never a pass
    summary: str
    findings: list[Finding]
    extraction: LabelExtraction | None
    model: str | None
    rules_version: str | None
    prompt_version: str | None
    cache_hit: bool | None
    duration_ms: int | None
    error: CheckError | None = None
