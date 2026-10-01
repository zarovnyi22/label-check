"""Contracts accept the model's real answers; unknown or invented values become null."""

import pytest
from pydantic import ValidationError

from app.schemas import LabelExtraction, Nutrition, Photo, ProductSpec
from tests.spike_outputs import P02, P03, P16, P17


@pytest.mark.parametrize("raw", [P02, P03, P16, P17])
def test_spike_answers_validate(raw):
    extraction = LabelExtraction.model_validate_json(raw)
    assert extraction.photos
    assert extraction.ingredients_marked.text


def test_spike_fields():
    p16 = LabelExtraction.model_validate_json(P16)
    assert p16.emphasis_resolvable is True
    assert p16.nutrition is None
    assert p16.ingredients_marked.photo_index == 1
    p03 = LabelExtraction.model_validate_json(P03)
    assert p03.nutrition.per == "100ml"
    assert p03.nutrition.fibre is None
    # The first draft prompt said `emphasis_visible`: an unknown key is dropped, the
    # contract field stays null (unknown), not False.
    assert p03.emphasis_resolvable is None
    assert p03.may_contain_text is None


def test_everything_may_be_null():
    empty = LabelExtraction.model_validate({})
    assert empty.model_dump() == {
        "photos": None,
        "emphasis_resolvable": None,
        "ingredients_marked": None,
        "may_contain_text": None,
        "nutrition": None,
        "other_text": None,
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [("100g", "100g"), ("PORTION", "portion"), ("100 g", None), ("null", None), (None, None)],
)
def test_unknown_per_becomes_null(value, expected):
    assert Nutrition(per=value).per == expected


def test_unknown_photo_side_and_quality():
    photo = Photo.model_validate({"index": 0, "side": "top", "quality": "great"})
    assert photo.side == "unknown"
    assert photo.quality is None  # no hint, never "ok"


def test_nutrition_numbers_stay_strings():
    assert Nutrition.model_validate({"sugars": 0.5, "fat": 3}).model_dump()["sugars"] == "0.5"


def test_product_spec_example_from_spec():
    spec = ProductSpec.model_validate(
        {
            "product_name": "Йогурт полуничний 2.5%",
            "form": "solid",
            "ingredients": [
                {"name": "молоко", "allergens": ["milk"]},
                {"name": "цукор", "allergens": []},
            ],
            "may_contain": ["nuts"],
            "nutrition_per_100": {"energy_kcal": 82, "fat": 2.0, "sugars": 13.3},
        }
    )
    assert spec.ingredients[0].allergens == ["milk"]
    assert spec.nutrition_per_100.salt is None


@pytest.mark.parametrize(
    "bad",
    [
        {"ingredients": [{"name": "молоко", "allergens": ["lactose"]}]},  # not a category
        {"may_contain": ["gluten"]},
        {"form": "powder"},
        {"nutrition_per_100": {"fat": -1}},
        {"ingredients": [{"name": ""}]},
        {"allergens": ["milk"]},  # typo in a field name must not be silently ignored
        {"ingredients": [{"name": "молоко", "alergens": ["milk"]}]},
        {"nutrition_per_100": {"sugar": 5}},
    ],
)
def test_product_spec_rejects_bad_input(bad):
    with pytest.raises(ValidationError):
        ProductSpec.model_validate(bad)
