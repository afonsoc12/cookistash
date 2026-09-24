from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from cookistash.cookidoo.models import Recipe as CookidooRecipe
from cookistash.cookidoo.models import ScrapedRecipe
from cookistash.mealie.client import MealieClient
from cookistash.mealie.models import Food, Source, Unit
from cookistash.mealie.transformer import (
    MealieTransformer,
    _build_nutrition,
    _format_time,
    _normalise_quantity,
    _parse_times,
    _strip_html,
)


class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_strips_surrounding_whitespace(self):
        assert _strip_html("  <p>text</p>  ") == "text"

    def test_plain_text_untouched(self):
        assert _strip_html("no tags here") == "no tags here"


class TestNormaliseQuantity:
    def test_uses_value_when_present(self):
        assert _normalise_quantity({"value": 5}) == 5

    def test_averages_from_to_range(self):
        assert _normalise_quantity({"from": 2, "to": 4}) == 3

    def test_raises_on_unrecognised_shape(self):
        with pytest.raises(NotImplementedError):
            _normalise_quantity({"unexpected": 1})


class TestFormatTime:
    def test_no_comment(self):
        assert _format_time({"quantity": {"value": 600}, "comment": ""}) == "10 mins"

    def test_with_comment(self):
        result = _format_time({"quantity": {"value": 60}, "comment": "resting"})
        assert result == "1 mins resting"

    def test_missing_comment_key(self):
        assert _format_time({"quantity": {"value": 120}}) == "2 mins"


class TestParseTimes:
    def test_parses_both_times(self):
        times = [
            {"type": "activeTime", "comment": "", "quantity": {"value": 600}},
            {"type": "totalTime", "comment": "", "quantity": {"value": 36000}},
        ]
        total, prep = _parse_times(times)
        assert total == "600 mins"
        assert prep == "10 mins"

    def test_raises_on_missing_type(self):
        with pytest.raises(TypeError):
            _parse_times([{"type": "activeTime", "comment": "", "quantity": {"value": 60}}])


class TestBuildNutrition:
    def test_maps_known_keys(self):
        groups = [
            {
                "recipeNutritions": [
                    {
                        "nutritions": [
                            {"type": "kcal", "number": 200},
                            {"type": "protein", "number": 10},
                            {"type": "unknownType", "number": 5},
                        ]
                    }
                ]
            }
        ]
        result = _build_nutrition(groups)
        assert result == {"calories": "200", "proteinContent": "10"}

    def test_empty_groups_returns_empty_dict(self):
        assert _build_nutrition([]) == {}

    def test_none_returns_empty_dict(self):
        assert _build_nutrition(None) == {}

    def test_malformed_shape_returns_empty_dict(self):
        assert _build_nutrition([{"recipeNutritions": [{}]}]) == {}


def _raw_recipe_data(**overrides):
    data = {
        "title": "Gazpacho",
        "descriptiveAssets": [{"landscape": "https://img.example.com/{transformation}/img.jpg"}],
        "servingSize": {"quantity": {"value": 4}, "unitNotation": "servings"},
        "times": [
            {"type": "activeTime", "comment": "", "quantity": {"value": 600}},
            {"type": "totalTime", "comment": "", "quantity": {"value": 1200}},
        ],
        "categories": [{"title": "Soups"}],
        "tags": [{"name": "cold"}],
        "recipeUtensils": [{"utensilNotation": "Blender"}],
        "difficulty": "Easy",
        "additionalInformation": [{"content": "<p>Best served <b>chilled</b>.</p>"}],
        "nutritionGroups": [{"recipeNutritions": [{"nutritions": [{"type": "kcal", "number": 150}]}]}],
        "recipeIngredientGroups": [
            {
                "title": "Main",
                "recipeIngredients": [
                    {
                        "unitNotation": "g",
                        "unit_ref": "unit-g",
                        "ingredient_ref": "ing-tomato",
                        "ingredientNotation": "tomatoes",
                        "quantity": {"value": 500},
                        "preparation": "chopped",
                    },
                    {
                        "unitNotation": "",
                        "unit_ref": "",
                        "ingredient_ref": "ing-salt",
                        "ingredientNotation": "salt",
                        "quantity": {"value": 1},
                        "preparation": "",
                    },
                ],
            }
        ],
        "recipeStepGroups": [
            {
                "title": "1",
                "recipeSteps": [
                    {"title": "Step 1", "formattedText": "Blend everything"},
                    {"title": "Step 2", "formattedText": "Chill and serve"},
                ],
            }
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture
def cookidoo_recipe():
    return CookidooRecipe.objects.create(
        id="r123", name="Gazpacho", language="en", markets=[], status="ok", publication_date=datetime.now()
    )


@pytest.fixture
def scrape(cookidoo_recipe):
    return ScrapedRecipe.objects.create(
        recipe=cookidoo_recipe, success=True, raw_data=_raw_recipe_data(), url="https://cookidoo.example.com/r123"
    )


@pytest.fixture
def mealie_source():
    return Source.objects.create(name="M", api_url="https://mealie.example.com", api_token="t")


@pytest.mark.django_db
class TestMealieTransformerTransform:
    def test_builds_ingredients_food_and_units(self, scrape, mealie_source):
        transformer = MealieTransformer.__new__(MealieTransformer)
        transformer.mealie_client = MagicMock()

        mealie_recipe = transformer.transform(scrape)

        ingredients = list(mealie_recipe.recipe_ingredient.select_related("food", "unit").order_by("pk"))
        assert len(ingredients) == 2
        by_food = {i.food.name: i for i in ingredients}

        tomatoes = by_food["tomatoes"]
        assert tomatoes.food.cookidoo_ref == "ing-tomato"
        assert tomatoes.unit.name == "g"
        assert tomatoes.quantity == 500
        assert tomatoes.note == "chopped"
        assert tomatoes.title == "Main"

        salt = by_food["salt"]
        # second ingredient in the same group has no group title (dedup'd)
        assert salt.title is None
        # no unit text -> no Unit created for it
        assert salt.unit is None

    def test_populates_recipe_fields(self, scrape, mealie_source):
        transformer = MealieTransformer.__new__(MealieTransformer)
        transformer.mealie_client = MagicMock()

        mealie_recipe = transformer.transform(scrape)

        assert mealie_recipe.name == "Gazpacho"
        assert mealie_recipe.image_url == "https://img.example.com/t_web_rdp_recipe_584x480_1_5x/img.jpg"
        assert mealie_recipe.recipe_servings == 4
        assert mealie_recipe.total_time == "20 mins"
        assert mealie_recipe.prep_time == "10 mins"
        assert mealie_recipe.recipe_category == [{"name": "Soups"}]
        assert mealie_recipe.tags == [{"name": "cold"}]
        assert mealie_recipe.tools == [{"name": "Blender"}]
        assert {"title": "Difficulty", "text": "Easy"} in mealie_recipe.notes
        assert {"title": "", "text": "Best served chilled."} in mealie_recipe.notes
        assert mealie_recipe.nutrition == {"calories": "150"}
        assert mealie_recipe.extras == {"cookidooId": "r123", "cookidooUrl": scrape.url}

    def test_builds_instructions_in_order(self, scrape, mealie_source):
        from cookistash.mealie.models import Instruction

        transformer = MealieTransformer.__new__(MealieTransformer)
        transformer.mealie_client = MagicMock()

        mealie_recipe = transformer.transform(scrape)

        instructions = list(Instruction.objects.filter(recipe=mealie_recipe).order_by("pk"))
        assert len(instructions) == 2
        assert instructions[0].formatted_text == "Blend everything"
        assert instructions[1].formatted_text == "Chill and serve"

    def test_rerunning_replaces_ingredients_and_instructions(self, scrape, mealie_source):
        from cookistash.mealie.models import Instruction

        transformer = MealieTransformer.__new__(MealieTransformer)
        transformer.mealie_client = MagicMock()
        transformer.transform(scrape)

        scrape.raw_data = _raw_recipe_data(
            recipeIngredientGroups=[
                {
                    "title": "Main",
                    "recipeIngredients": [
                        {
                            "unitNotation": "kg",
                            "unit_ref": "unit-kg",
                            "ingredient_ref": "ing-tomato",
                            "ingredientNotation": "tomatoes",
                            "quantity": {"value": 1},
                            "preparation": "",
                        }
                    ],
                }
            ],
            recipeStepGroups=[{"title": "1", "recipeSteps": [{"title": "Only step", "formattedText": "Do it"}]}],
        )
        mealie_recipe = transformer.transform(scrape)

        assert mealie_recipe.recipe_ingredient.count() == 1
        assert Instruction.objects.filter(recipe=mealie_recipe).count() == 1

    def test_reuses_food_and_unit_by_cookidoo_ref_across_recipes(self, mealie_source):
        recipe1 = CookidooRecipe.objects.create(
            id="r1", name="A", language="en", markets=[], status="ok", publication_date=datetime.now()
        )
        recipe2 = CookidooRecipe.objects.create(
            id="r2", name="B", language="en", markets=[], status="ok", publication_date=datetime.now()
        )
        scrape1 = ScrapedRecipe.objects.create(recipe=recipe1, success=True, raw_data=_raw_recipe_data())
        data2 = _raw_recipe_data(title="Other soup")
        # Same ingredient/unit refs, different display text
        data2["recipeIngredientGroups"][0]["recipeIngredients"][0]["ingredientNotation"] = "tomato"
        data2["recipeIngredientGroups"][0]["recipeIngredients"][0]["unitNotation"] = "grams"
        scrape2 = ScrapedRecipe.objects.create(recipe=recipe2, success=True, raw_data=data2)

        transformer = MealieTransformer.__new__(MealieTransformer)
        transformer.mealie_client = MagicMock()
        transformer.transform(scrape1)
        transformer.transform(scrape2)

        assert Food.objects.filter(cookidoo_ref="ing-tomato").count() == 1
        assert Unit.objects.filter(cookidoo_ref="unit-g").count() == 1


@pytest.mark.django_db
class TestMealieTransformerInit:
    def test_uses_default_mealie_source(self, mealie_source):
        with patch.object(MealieClient, "test", return_value=True):
            transformer = MealieTransformer()
        assert transformer.mealie_client.url == mealie_source.api_url


@pytest.mark.django_db
class TestCreateInMealie:
    def test_pushes_distinct_foods_and_units_then_recipe(self, scrape, mealie_source):
        transformer = MealieTransformer.__new__(MealieTransformer)
        transformer.mealie_client = MagicMock()
        mealie_recipe = MealieTransformer.transform(transformer, scrape)

        transformer.create_in_mealie(mealie_recipe)

        assert transformer.mealie_client.create_food.call_count == 2
        assert transformer.mealie_client.create_unit.call_count == 1
        transformer.mealie_client.create_or_update_recipe.assert_called_once_with(mealie_recipe)
