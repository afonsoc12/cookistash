from datetime import datetime
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import models

from cookistash.mealie.models import Food, Ingredient, Instruction, ModelMealieApi, Source, Unit
from cookistash.mealie.models import Recipe as MealieRecipe

pytestmark = pytest.mark.django_db


class TestModelMealieApi:
    # Dynamically creates/drops a table via schema_editor in `concrete_model`
    # below - needs its own (non-atomic) transaction, since SQLite refuses
    # DDL with FK checks enabled inside the transaction pytest-django's
    # default `django_db` marker wraps every test in.
    pytestmark = pytest.mark.django_db(transaction=True)

    @pytest.fixture
    def concrete_model(self, django_db_blocker):
        """
        Dynamically create a temporary concrete subclass of ModelMealieApi.
        Django requires a managed model for ORM operations.
        """
        with django_db_blocker.unblock():

            class ConcreteModel(ModelMealieApi):
                id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
                name = models.CharField(max_length=255)
                unit_ref = models.CharField(max_length=255, blank=True, null=True)
                ingredient_notation = models.CharField(max_length=255, blank=True, null=True)

                class Meta:
                    app_label = "testapp"
                    managed = True

            # Create table manually for this transient model
            from django.db import connection

            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(ConcreteModel)

            yield ConcreteModel

            # Drop the table after the test
            with connection.schema_editor() as schema_editor:
                schema_editor.delete_model(ConcreteModel)

    @pytest.fixture
    def api_data(self):
        return {
            "id": str(uuid4()),
            "name": "Parmesan cheese",
            "unit_Ref": "1092-unit-rdpf3",
            "ingredientNotation": "Grated cheese",
        }

    def test_get_or_create_from_api_data_creates(self, concrete_model, api_data):
        obj, created = concrete_model.get_or_create_from_api_data(api_data)

        assert created is True
        assert obj.name == "Parmesan cheese"
        assert obj.unit_ref == "1092-unit-rdpf3"
        assert obj.ingredient_notation == "Grated cheese"
        assert concrete_model.objects.count() == 1

    def test_get_or_create_from_api_data_gets(self, concrete_model, api_data):
        existing = concrete_model.objects.create(
            name=api_data["name"], unit_ref=api_data["unit_Ref"], ingredient_notation=api_data["ingredientNotation"]
        )

        obj, created = concrete_model.get_or_create_from_api_data(api_data)

        assert created is False
        assert obj.id == existing.id
        assert concrete_model.objects.count() == 1

    def test_get_or_create_from_api_data_ignores_invalid_fields(self, concrete_model, api_data):
        bad_data = {**api_data, "extraField": "should be ignored"}

        obj, created = concrete_model.get_or_create_from_api_data(bad_data)

        assert created is True
        assert not hasattr(obj, "extraField") or not hasattr(obj, "extra_field")
        assert obj.name == "Parmesan cheese"

    def test_to_api_data_converts_to_camelcase(self, concrete_model):
        obj = concrete_model.objects.create(
            name="Parmesan cheese",
            unit_ref="1092-unit-rdpf3",
            ingredient_notation="Grated cheese",
        )

        data = obj.to_api_data()

        assert "id" in data
        assert data["id"] == str(obj.id)
        assert data["unitRef"] == "1092-unit-rdpf3"
        assert data["ingredientNotation"] == "Grated cheese"
        assert data["name"] == "Parmesan cheese"

    def test_to_api_data_excludes_requested_fields(self, concrete_model):
        obj = concrete_model.objects.create(name="Salt", unit_ref="ref-1", ingredient_notation="Fine salt")
        data = obj.to_api_data(exclude=["unit_ref"])
        assert "unitRef" not in data
        assert data["name"] == "Salt"

    def test_to_api_data_skips_none_values(self, concrete_model):
        obj = concrete_model.objects.create(name="Salt", unit_ref=None, ingredient_notation=None)
        data = obj.to_api_data()
        assert "unitRef" not in data
        assert "ingredientNotation" not in data


class TestModelMealieApiRelations:
    """Covers the FK/M2M branches of to_api_data() via real concrete models
    (Ingredient -> Food/Unit FKs, Recipe -> Ingredient M2M, Recipe -> Cookidoo
    Recipe FK without its own to_api_data)."""

    @pytest.fixture
    def cookidoo_recipe(self):
        from cookistash.cookidoo.models import Recipe as CookidooRecipe

        return CookidooRecipe.objects.create(
            id="r123", name="Gazpacho", language="en", markets=[], status="ok", publication_date=datetime.now()
        )

    @pytest.fixture
    def scrape(self, cookidoo_recipe):
        from cookistash.cookidoo.models import ScrapedRecipe

        return ScrapedRecipe.objects.create(recipe=cookidoo_recipe, success=True)

    def test_fk_to_related_object_with_to_api_data_is_nested(self):
        food = Food.objects.create(name="Salt")
        unit = Unit.objects.create(name="g")
        ingredient = Ingredient.objects.create(reference_id=uuid4(), quantity=5, food=food, unit=unit)

        data = ingredient.to_api_data()

        assert data["food"]["name"] == "Salt"
        assert data["unit"]["name"] == "g"

    def test_fk_to_related_object_without_to_api_data_uses_pk(self, cookidoo_recipe, scrape):
        recipe = MealieRecipe.objects.create(
            recipe=cookidoo_recipe, scraped_recipe=scrape, name="Gazpacho", image_url="", org_url=""
        )
        data = recipe.to_api_data()
        assert data["recipe"] == cookidoo_recipe.pk

    def test_null_fk_is_omitted_from_output(self):
        # Note: to_api_data() skips any field whose value is None before it
        # ever checks field.is_relation (see the `if value is None: continue`
        # above), so a null FK is dropped entirely rather than serialized as
        # `null` - the explicit None-handling further down in the relation
        # branch is unreachable dead code.
        ingredient = Ingredient.objects.create(reference_id=uuid4(), quantity=1, food=None, unit=None)
        data = ingredient.to_api_data()
        assert "food" not in data
        assert "unit" not in data

    def test_many_to_many_serializes_related_objects(self, cookidoo_recipe, scrape):
        food = Food.objects.create(name="Salt")
        ingredient = Ingredient.objects.create(reference_id=uuid4(), quantity=1, food=food)
        recipe = MealieRecipe.objects.create(
            recipe=cookidoo_recipe, scraped_recipe=scrape, name="Gazpacho", image_url="", org_url=""
        )
        recipe.recipe_ingredient.add(ingredient)

        data = recipe.to_api_data()

        assert len(data["recipeIngredient"]) == 1
        assert data["recipeIngredient"][0]["quantity"] == 1


class TestSource:
    def test_create_source(self):
        source = Source.objects.create(name="Mealie", api_url="https://example.com", api_token="verysecrettoken")
        assert source.pk is not None
        assert str(source) == "Mealie"

    def test_second_source_rejected(self):
        url = "https://mealie.example.com"
        token = "verysecrettoken"
        Source.objects.create(name="Source 1", api_url=url, api_token=token)
        with pytest.raises(ValidationError):
            Source.objects.create(name="Source 2", api_url=url, api_token=token)

    def test_existing_source_can_be_updated(self):
        source = Source.objects.create(name="Source 1", api_url="https://example.com", api_token="verysecrettoken")
        source.group_slug = "other"
        source.save()
        source.refresh_from_db()
        assert source.group_slug == "other"

    def test_recipe_url_uses_public_url_when_set(self):
        source = Source.objects.create(
            name="M",
            api_url="http://mealie:9000",
            public_url="https://mealie.example.com/",
            group_slug="home",
            api_token="t",
        )
        assert source.recipe_url("gazpacho") == "https://mealie.example.com/g/home/r/gazpacho"

    def test_recipe_url_falls_back_to_api_url(self):
        source = Source.objects.create(name="M", api_url="http://mealie:9000/", group_slug="home", api_token="t")
        assert source.recipe_url("gazpacho") == "http://mealie:9000/g/home/r/gazpacho"


class TestCookidooRefLookupMixin:
    def test_get_or_create_by_ref_creates_when_missing(self):
        food, created = Food.get_or_create_by_ref("ref-1", "Salt")
        assert created is True
        assert food.cookidoo_ref == "ref-1"
        assert food.name == "Salt"

    def test_get_or_create_by_ref_reuses_existing_ref(self):
        first, _ = Food.get_or_create_by_ref("ref-1", "Salt")
        second, created = Food.get_or_create_by_ref("ref-1", "Different display text")
        assert created is False
        assert second.pk == first.pk
        assert second.name == "Salt"

    def test_get_or_create_by_ref_falls_back_to_name_when_no_ref(self):
        food, created = Food.get_or_create_by_ref(None, "Pepper")
        assert created is True
        assert food.cookidoo_ref is None
        assert food.name == "Pepper"

        food2, created2 = Food.get_or_create_by_ref("", "Pepper")
        assert created2 is False
        assert food2.pk == food.pk

    def test_to_api_data_uses_mealie_id_when_set(self):
        mealie_id = uuid4()
        food = Food.objects.create(name="Salt", mealie_id=mealie_id)
        data = food.to_api_data()
        assert data["id"] == str(mealie_id)
        assert "cookidooRef" not in data
        assert "mealieId" not in data

    def test_to_api_data_omits_id_when_no_mealie_id(self):
        food = Food.objects.create(name="Salt")
        data = food.to_api_data()
        assert "id" not in data


class TestFood:
    def test_str(self):
        food = Food.objects.create(name="Salt")
        assert str(food) == "Salt"


class TestUnit:
    def test_str(self):
        unit = Unit.objects.create(name="g")
        assert str(unit) == "g"


class TestIngredient:
    def test_str_with_unit_and_note(self):
        food = Food.objects.create(name="Salt")
        unit = Unit.objects.create(name="g", abbreviation="g")
        ingredient = Ingredient.objects.create(reference_id=uuid4(), quantity=5, food=food, unit=unit, note="fine")
        assert str(ingredient) == "5 g Salt (fine)"

    def test_str_without_unit_or_food_or_note(self):
        ingredient = Ingredient.objects.create(reference_id=uuid4(), quantity=1)
        assert str(ingredient) == "1  "

    def test_str_uses_name_when_no_abbreviation(self):
        food = Food.objects.create(name="Salt")
        unit = Unit.objects.create(name="grams")
        ingredient = Ingredient.objects.create(reference_id=uuid4(), quantity=2, food=food, unit=unit)
        assert "grams" in str(ingredient)


@pytest.mark.django_db
class TestMealieRecipe:
    @pytest.fixture
    def cookidoo_recipe(self):
        from cookistash.cookidoo.models import Recipe as CookidooRecipe

        return CookidooRecipe.objects.create(
            id="r123", name="Gazpacho", language="en", markets=[], status="ok", publication_date=datetime.now()
        )

    @pytest.fixture
    def scrape(self, cookidoo_recipe):
        from cookistash.cookidoo.models import ScrapedRecipe

        return ScrapedRecipe.objects.create(recipe=cookidoo_recipe, success=True)

    def test_save_defaults_slug_to_cookidoo_recipe_id(self, cookidoo_recipe, scrape):
        recipe = MealieRecipe.objects.create(
            recipe=cookidoo_recipe, scraped_recipe=scrape, name="Gazpacho", image_url="", org_url=""
        )
        assert recipe.slug == "r123"

    def test_str(self, cookidoo_recipe, scrape):
        recipe = MealieRecipe.objects.create(
            recipe=cookidoo_recipe, scraped_recipe=scrape, name="Gazpacho", image_url="", org_url=""
        )
        assert str(recipe) == "Gazpacho (r123)"


class TestInstruction:
    def test_parse_instruction_replaces_pua_chars(self):
        text = "Stir " + "" + " then add " + "" + " cheese"
        assert Instruction.parse_instruction(text) == "Stir 🔄 then add 🥄 cheese"

    def test_parse_instruction_leaves_normal_text_untouched(self):
        assert Instruction.parse_instruction("Chop everything") == "Chop everything"

    @pytest.mark.django_db
    def test_str(self):
        from cookistash.cookidoo.models import Recipe as CookidooRecipe
        from cookistash.cookidoo.models import ScrapedRecipe

        cookidoo_recipe = CookidooRecipe.objects.create(
            id="r123", name="Gazpacho", language="en", markets=[], status="ok", publication_date=datetime.now()
        )
        scrape = ScrapedRecipe.objects.create(recipe=cookidoo_recipe, success=True)
        recipe = MealieRecipe.objects.create(
            recipe=cookidoo_recipe, scraped_recipe=scrape, name="Gazpacho", image_url="", org_url=""
        )
        instruction = Instruction.objects.create(recipe=recipe, title="Prep", summary="Step 1", formatted_text="Chop")
        assert str(instruction) == "([Prep] Step 1: Chop"
