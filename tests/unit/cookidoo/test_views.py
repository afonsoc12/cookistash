from datetime import datetime
from unittest.mock import patch

import pytest
from django.urls import reverse

from cookistash.cookidoo.models import Recipe, ScrapedRecipe, Source

pytestmark = pytest.mark.django_db


@pytest.fixture
def source():
    return Source.objects.create(name="S", url="https://example.com", locale="en-GB")


@pytest.fixture
def recipe(source):
    return Recipe.objects.create(
        id="r123",
        name="Gazpacho",
        language="en",
        markets=[],
        status="ok",
        publication_date=datetime.now(),
        source=source,
    )


class TestDiscover:
    def test_no_source_configured(self, client):
        resp = client.get(reverse("cookidoo:discover"))
        assert resp.status_code == 200
        assert resp.context["has_cookidoo_source"] is False
        assert resp.context["results"] == []

    def test_lists_results_and_flags_already_scraped(self, client):
        Source.objects.create(name="S", url="https://example.com", locale="en-GB")
        Recipe.objects.create(
            id="r1", name="Known", language="en", markets=[], status="ok", publication_date=datetime.now()
        )
        mock_results = [
            {"id": "r1", "title": "Known"},
            {"id": "r2", "title": "New"},
        ]
        with (
            patch("cookistash.cookidoo.views.CookidooClient.test", return_value=True),
            patch("cookistash.cookidoo.views.CookidooClient.search", return_value=mock_results),
        ):
            resp = client.get(reverse("cookidoo:discover"), {"category": "cat1"})

        assert resp.status_code == 200
        by_id = {r["id"]: r for r in resp.context["results"]}
        assert by_id["r1"]["already_scraped"] is True
        assert by_id["r2"]["already_scraped"] is False

    def test_fetch_error_is_surfaced_not_raised(self, client):
        Source.objects.create(name="S", url="https://example.com", locale="en-GB")
        with patch("cookistash.cookidoo.views.CookidooClient.__init__", side_effect=Exception("boom")):
            resp = client.get(reverse("cookidoo:discover"))

        assert resp.status_code == 200
        assert "boom" in resp.context["fetch_error"]

    def test_country_defaults_to_source_market_when_unset(self, client):
        Source.objects.create(name="S", url="https://cookidoo.pt/", locale="pt-PT")
        with (
            patch("cookistash.cookidoo.views.CookidooClient.test", return_value=True),
            patch("cookistash.cookidoo.views.CookidooClient.search", return_value=[]) as mock_search,
        ):
            resp = client.get(reverse("cookidoo:discover"))

        assert resp.context["country"] == "pt"
        mock_search.assert_called_once_with(category=None, country="pt", query=None, page=0, limit=24)

    def test_explicit_empty_country_means_all_countries(self, client):
        Source.objects.create(name="S", url="https://cookidoo.pt/", locale="pt-PT")
        with (
            patch("cookistash.cookidoo.views.CookidooClient.test", return_value=True),
            patch("cookistash.cookidoo.views.CookidooClient.search", return_value=[]) as mock_search,
        ):
            resp = client.get(reverse("cookidoo:discover"), {"country": ""})

        assert resp.context["country"] == ""
        mock_search.assert_called_once_with(category=None, country=None, query=None, page=0, limit=24)


class TestDiscoverImport:
    def test_import_success_redirects_to_discover(self, client):
        with patch("cookistash.cookidoo.views.scrape_recipe.apply") as mock_apply:
            mock_apply.return_value.get.return_value = "some-task-id"
            resp = client.post(
                reverse("cookidoo:discover_import", args=["r99"]),
                {"category": "cat1", "page": "2"},
            )

        assert resp.status_code == 200
        mock_apply.assert_called_once_with(args=("r99",))

    def test_import_failure_shows_message(self, client):
        with patch("cookistash.cookidoo.views.scrape_recipe.apply", side_effect=Exception("scrape failed")):
            resp = client.post(reverse("cookidoo:discover_import", args=["r99"]), {})

        assert resp.status_code == 200
        messages = list(resp.context["messages"])
        assert any("scrape failed" in str(m) for m in messages)


class TestRecipeList:
    def test_empty_state(self, client):
        resp = client.get(reverse("cookidoo:recipe_list"))
        assert resp.status_code == 200
        assert list(resp.context["page"].object_list) == []
        assert resp.context["has_cookidoo_source"] is False
        assert resp.context["has_mealie_source"] is False

    def test_lists_recipes_ordered_by_last_scraped(self, client, recipe, source):
        other = Recipe.objects.create(
            id="r456",
            name="Toast",
            language="en",
            markets=[],
            status="ok",
            publication_date=datetime.now(),
            source=source,
        )
        resp = client.get(reverse("cookidoo:recipe_list"))
        ids = [r["recipe"].id for r in resp.context["rows"]]
        assert set(ids) == {recipe.id, other.id}

    def test_query_filters_by_name(self, client, recipe, source):
        Recipe.objects.create(
            id="r456",
            name="Toast",
            language="en",
            markets=[],
            status="ok",
            publication_date=datetime.now(),
            source=source,
        )
        resp = client.get(reverse("cookidoo:recipe_list"), {"q": "gazp"})
        ids = [r["recipe"].id for r in resp.context["rows"]]
        assert ids == ["r123"]
        assert resp.context["query"] == "gazp"

    def test_has_mealie_source_true_when_configured(self, client, recipe):
        from cookistash.mealie.models import Source as MealieSource

        MealieSource.objects.create(name="M", api_url="https://mealie.example.com", api_token="t", is_default=True)
        resp = client.get(reverse("cookidoo:recipe_list"))
        assert resp.context["has_mealie_source"] is True


class TestRecipeDetail:
    def test_404_for_unknown_recipe(self, client):
        resp = client.get(reverse("cookidoo:recipe_detail", args=["r999"]))
        assert resp.status_code == 404

    def test_recipe_with_no_scrape_yet(self, client, recipe):
        resp = client.get(reverse("cookidoo:recipe_detail", args=[recipe.id]))
        assert resp.status_code == 200
        assert resp.context["latest_scrape"] is None
        assert resp.context["raw_json"] is None
        assert resp.context["ingredients"] == []
        assert resp.context["instructions"] == []
        assert resp.context["nutrition_items"] == []

    def test_recipe_with_scrape_but_not_synced_to_mealie(self, client, recipe):
        ScrapedRecipe.objects.create(recipe=recipe, success=True, raw_data={"title": "Gazpacho"})
        resp = client.get(reverse("cookidoo:recipe_detail", args=[recipe.id]))
        assert resp.status_code == 200
        assert resp.context["latest_scrape"] is not None
        assert resp.context["raw_json"] is not None
        assert resp.context["mealie_recipe"] is None

    def test_recipe_with_mealie_data_shows_ingredients_and_nutrition(self, client, recipe):
        from cookistash.mealie.models import Food, Ingredient
        from cookistash.mealie.models import Recipe as MealieRecipe

        scrape = ScrapedRecipe.objects.create(recipe=recipe, success=True, raw_data={"title": "Gazpacho"})
        mealie_recipe = MealieRecipe.objects.create(
            recipe=recipe,
            scraped_recipe=scrape,
            name="Gazpacho",
            image_url="",
            org_url="",
            nutrition={"calories": "150", "proteinContent": ""},
        )
        food = Food.objects.create(name="Tomato")
        ingredient = Ingredient.objects.create(
            reference_id="11111111-1111-1111-1111-111111111111", quantity=2, food=food
        )
        mealie_recipe.recipe_ingredient.add(ingredient)

        resp = client.get(reverse("cookidoo:recipe_detail", args=[recipe.id]))

        assert resp.status_code == 200
        assert len(resp.context["ingredients"]) == 1
        # empty-value nutrition entries are dropped, only calories should show
        assert len(resp.context["nutrition_items"]) == 1
        assert resp.context["nutrition_items"][0]["label"] == "Calories"

    def test_mealie_recipe_url_built_when_source_and_slug_present(self, client, recipe):
        from cookistash.mealie.models import Recipe as MealieRecipe
        from cookistash.mealie.models import Source as MealieSource

        MealieSource.objects.create(
            name="M",
            api_url="https://mealie.example.com",
            public_url="https://mealie.example.com",
            group_slug="home",
            api_token="t",
            is_default=True,
        )
        scrape = ScrapedRecipe.objects.create(recipe=recipe, success=True, raw_data={})
        MealieRecipe.objects.create(
            recipe=recipe,
            scraped_recipe=scrape,
            name="Gazpacho",
            image_url="",
            org_url="",
            mealie_slug="gazpacho-slug",
        )
        resp = client.get(reverse("cookidoo:recipe_detail", args=[recipe.id]))
        assert resp.context["mealie_recipe_url"] == "https://mealie.example.com/g/home/r/gazpacho-slug"


class TestRecipeScrapeNew:
    def test_blank_input_is_a_silent_noop(self, client):
        resp = client.post(reverse("cookidoo:recipe_scrape_new"), {"recipe_id": ""}, follow=True)
        assert resp.status_code == 200
        assert list(get_messages_for(resp)) == []

    def test_unparseable_input_shows_error(self, client):
        resp = client.post(reverse("cookidoo:recipe_scrape_new"), {"recipe_id": "not an id"}, follow=True)
        messages = list(get_messages_for(resp))
        assert any("Couldn't find a recipe ID" in str(m) for m in messages)

    def test_no_source_configured_shows_error(self, client):
        resp = client.post(reverse("cookidoo:recipe_scrape_new"), {"recipe_id": "r123456"}, follow=True)
        messages = list(get_messages_for(resp))
        assert any("No Cookidoo source" in str(m) for m in messages)

    def test_valid_input_triggers_scrape(self, client, source):
        with patch("cookistash.cookidoo.views.scrape_recipe.apply") as mock_apply:
            mock_apply.return_value.get.return_value = "task-id"
            resp = client.post(reverse("cookidoo:recipe_scrape_new"), {"recipe_id": "r123456"}, follow=True)
        mock_apply.assert_called_once_with(args=("r123456",))
        messages = list(get_messages_for(resp))
        assert any("Scraped r123456" in str(m) for m in messages)

    def test_scrape_failure_shows_error(self, client, source):
        with patch("cookistash.cookidoo.views.scrape_recipe.apply", side_effect=RuntimeError("boom")):
            resp = client.post(reverse("cookidoo:recipe_scrape_new"), {"recipe_id": "r123456"}, follow=True)
        messages = list(get_messages_for(resp))
        assert any("Scrape of r123456 failed" in str(m) for m in messages)


class TestRecipeRescrape:
    def test_404_for_unknown_recipe(self, client):
        resp = client.post(reverse("cookidoo:recipe_rescrape", args=["r999"]))
        assert resp.status_code == 404

    def test_success(self, client, recipe):
        with patch("cookistash.cookidoo.views.scrape_recipe.apply") as mock_apply:
            mock_apply.return_value.get.return_value = "task-id"
            resp = client.post(reverse("cookidoo:recipe_rescrape", args=[recipe.id]))
        assert resp.status_code == 200

    def test_failure_renders_action_error(self, client, recipe):
        with patch("cookistash.cookidoo.views.scrape_recipe.apply", side_effect=RuntimeError("boom")):
            resp = client.post(reverse("cookidoo:recipe_rescrape", args=[recipe.id]))
        assert resp.status_code == 200
        assert b"boom" in resp.content

    def test_default_renders_list_card_partial(self, client, recipe):
        with patch("cookistash.cookidoo.views.scrape_recipe.apply") as mock_apply:
            mock_apply.return_value.get.return_value = "task-id"
            resp = client.post(reverse("cookidoo:recipe_rescrape", args=[recipe.id]))
        assert [t.name for t in resp.templates] == ["cookidoo/_recipe_card.html"]

    def test_hx_target_recipe_hero_renders_hero_partial(self, client, recipe):
        # The detail page's hero buttons hx-target="#recipe-hero" - htmx
        # sends the target id as this header, used to pick the partial that
        # actually matches the page doing the swap (see _card_or_hero_template).
        with patch("cookistash.cookidoo.views.scrape_recipe.apply") as mock_apply:
            mock_apply.return_value.get.return_value = "task-id"
            resp = client.post(reverse("cookidoo:recipe_rescrape", args=[recipe.id]), HTTP_HX_TARGET="recipe-hero")
        assert [t.name for t in resp.templates] == ["cookidoo/_recipe_hero.html"]


class TestRecipeSendToMealie:
    def test_404_for_unknown_recipe(self, client):
        resp = client.post(reverse("cookidoo:recipe_send_to_mealie", args=["r999"]))
        assert resp.status_code == 404

    def test_no_mealie_source_configured(self, client, recipe):
        resp = client.post(reverse("cookidoo:recipe_send_to_mealie", args=[recipe.id]))
        assert resp.status_code == 200
        assert b"No default Mealie source" in resp.content

    def test_success(self, client, recipe):
        from cookistash.mealie.models import Source as MealieSource

        MealieSource.objects.create(name="M", api_url="https://mealie.example.com", api_token="t", is_default=True)
        with patch("cookistash.cookidoo.views.send_to_mealie.apply") as mock_apply:
            mock_apply.return_value.get.return_value = "r123"
            resp = client.post(reverse("cookidoo:recipe_send_to_mealie", args=[recipe.id]))
        mock_apply.assert_called_once_with(args=(recipe.id,), kwargs={"force": True})
        assert resp.status_code == 200

    def test_failure_renders_action_error(self, client, recipe):
        from cookistash.mealie.models import Source as MealieSource

        MealieSource.objects.create(name="M", api_url="https://mealie.example.com", api_token="t", is_default=True)
        with patch("cookistash.cookidoo.views.send_to_mealie.apply", side_effect=RuntimeError("mealie down")):
            resp = client.post(reverse("cookidoo:recipe_send_to_mealie", args=[recipe.id]))
        assert resp.status_code == 200
        assert b"mealie down" in resp.content


def get_messages_for(response):
    from django.contrib.messages import get_messages

    return get_messages(response.wsgi_request)
