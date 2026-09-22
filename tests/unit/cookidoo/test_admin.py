import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import RequestFactory
from django.urls import reverse
from django_celery_results.models import TaskResult

from cookistash.cookidoo.admin import RecipeAdmin, ScrapedRecipeAdmin, UnfoldTaskResultAdmin
from cookistash.cookidoo.models import Recipe, Source
from cookistash.mealie.models import Recipe as MealieRecipe
from cookistash.mealie.models import Source as MealieSource

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user():
    return User.objects.create_superuser(username="admin", password="x", email="a@example.com")


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


class TestExtractRecipeId:
    def _admin(self):
        return UnfoldTaskResultAdmin(TaskResult, admin_site=None)

    def test_extracts_from_task_args(self):
        admin_obj = self._admin()
        task_result = MagicMock(task_args=json.dumps("('r96596',)"), task_kwargs=None)
        assert admin_obj._extract_recipe_id(task_result) == "r96596"

    def test_extracts_from_task_kwargs(self):
        admin_obj = self._admin()
        task_result = MagicMock(task_args=None, task_kwargs=json.dumps("{'recipe_id': 'r12345'}"))
        assert admin_obj._extract_recipe_id(task_result) == "r12345"

    def test_returns_none_when_neither_set(self):
        admin_obj = self._admin()
        task_result = MagicMock(task_args=None, task_kwargs=None)
        assert admin_obj._extract_recipe_id(task_result) is None

    def test_returns_none_on_malformed_json(self):
        admin_obj = self._admin()
        task_result = MagicMock(task_args="not json{{{", task_kwargs=None)
        assert admin_obj._extract_recipe_id(task_result) is None

    def test_returns_none_when_literal_eval_fails(self):
        admin_obj = self._admin()
        # Valid JSON string, but not a valid Python literal once unwrapped.
        task_result = MagicMock(task_args=json.dumps("not(a, valid, literal"), task_kwargs=None)
        assert admin_obj._extract_recipe_id(task_result) is None

    def test_returns_none_when_no_recipe_id_present(self):
        admin_obj = self._admin()
        task_result = MagicMock(task_args=json.dumps("('not-a-recipe-id',)"), task_kwargs=None)
        assert admin_obj._extract_recipe_id(task_result) is None


class TestTaskResultAdminDisplay:
    def _admin(self):
        return UnfoldTaskResultAdmin(TaskResult, admin_site=None)

    def test_short_task_name_strips_module_path(self):
        admin_obj = self._admin()
        obj = MagicMock(task_name="cookistash.cookidoo.tasks.scrape_recipe")
        assert admin_obj.short_task_name(obj) == "scrape_recipe"

    def test_short_task_name_handles_none(self):
        admin_obj = self._admin()
        obj = MagicMock(task_name=None)
        assert admin_obj.short_task_name(obj) == ""

    @pytest.mark.parametrize(
        "status,expected_color",
        [
            ("SUCCESS", "#1b7d4f"),
            ("FAILURE", "#c0392b"),
            ("STARTED", "#a06b00"),
            ("PENDING", "#837a70"),
            ("RETRY", "#a06b00"),
            ("UNKNOWN", "#837a70"),
        ],
    )
    def test_status_pill_colors(self, status, expected_color):
        admin_obj = self._admin()
        obj = MagicMock(status=status)
        html = admin_obj.status_pill(obj)
        assert expected_color in html
        assert status in html

    def test_recipe_link_with_recipe_id(self):
        admin_obj = self._admin()
        obj = MagicMock(task_args=json.dumps("('r96596',)"), task_kwargs=None)
        html = admin_obj.recipe_link(obj)
        assert "r96596" in html
        assert reverse("cookidoo:recipe_detail", args=["r96596"]) in html

    def test_recipe_link_without_recipe_id(self):
        admin_obj = self._admin()
        obj = MagicMock(task_args=None, task_kwargs=None)
        assert admin_obj.recipe_link(obj) == "-"

    def test_has_change_permission_always_false(self):
        admin_obj = self._admin()
        assert admin_obj.has_change_permission(MagicMock()) is False


class TestRecipeAdminDisplay:
    def _admin(self):
        return RecipeAdmin(Recipe, admin_site=None)

    def test_thumbnail_with_image(self, recipe):
        recipe.image_url = "https://example.com/img.jpg"
        admin_obj = self._admin()
        html = admin_obj.thumbnail(recipe)
        assert "https://example.com/img.jpg" in html

    def test_thumbnail_without_image(self, recipe):
        recipe.image_url = None
        admin_obj = self._admin()
        assert admin_obj.thumbnail(recipe) == "-"

    def test_mealie_sync_status_not_synced(self, recipe):
        admin_obj = self._admin()
        assert admin_obj.mealie_sync_status(recipe) == "not synced"

    def test_mealie_sync_status_synced_no_source(self, recipe):
        from cookistash.cookidoo.models import ScrapedRecipe

        scrape = ScrapedRecipe.objects.create(recipe=recipe, success=True)
        MealieRecipe.objects.create(
            recipe=recipe,
            scraped_recipe=scrape,
            name="Gazpacho",
            image_url="",
            org_url="",
            mealie_slug="gazpacho-slug",
        )
        admin_obj = self._admin()
        assert admin_obj.mealie_sync_status(recipe) == "synced (gazpacho-slug)"

    def test_mealie_sync_status_synced_with_source(self, recipe):
        from cookistash.cookidoo.models import ScrapedRecipe

        scrape = ScrapedRecipe.objects.create(recipe=recipe, success=True)
        MealieRecipe.objects.create(
            recipe=recipe,
            scraped_recipe=scrape,
            name="Gazpacho",
            image_url="",
            org_url="",
            mealie_slug="gazpacho-slug",
        )
        MealieSource.objects.create(
            name="M",
            api_url="https://mealie.example.com",
            public_url="https://mealie.example.com",
            group_slug="home",
            api_token="t",
            is_default=True,
        )
        admin_obj = self._admin()
        html = admin_obj.mealie_sync_status(recipe)
        assert "gazpacho-slug" in html
        assert "https://mealie.example.com/g/home/r/gazpacho-slug" in html


class TestRecipeAdminActions:
    def _admin(self):
        return RecipeAdmin(Recipe, admin_site=None)

    def _request(self, admin_user):
        rf = RequestFactory()
        request = rf.post("/admin/cookidoo/recipe/")
        request.user = admin_user
        request.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage

        request._messages = FallbackStorage(request)
        return request

    def test_rescrape_selected_no_source_configured(self, admin_user, recipe):
        Source.objects.all().delete()
        admin_obj = self._admin()
        request = self._request(admin_user)
        admin_obj.rescrape_selected(request, Recipe.objects.filter(pk=recipe.pk))
        messages = [str(m) for m in get_messages(request)]
        assert any("No Cookidoo source" in m for m in messages)

    def test_rescrape_selected_success(self, admin_user, recipe, source):
        admin_obj = self._admin()
        request = self._request(admin_user)
        with patch("cookistash.cookidoo.admin.scrape_recipe.apply") as mock_apply:
            mock_apply.return_value.get.return_value = "task-id"
            admin_obj.rescrape_selected(request, Recipe.objects.filter(pk=recipe.pk))
        messages = [str(m) for m in get_messages(request)]
        assert any("Re-scraped 1 recipe" in m for m in messages)

    def test_rescrape_selected_reports_failures(self, admin_user, recipe, source):
        admin_obj = self._admin()
        request = self._request(admin_user)
        with patch("cookistash.cookidoo.admin.scrape_recipe.apply", side_effect=RuntimeError("boom")):
            admin_obj.rescrape_selected(request, Recipe.objects.filter(pk=recipe.pk))
        messages = [str(m) for m in get_messages(request)]
        assert any("boom" in m for m in messages)

    def test_send_to_mealie_selected_no_source_configured(self, admin_user, recipe, source):
        admin_obj = self._admin()
        request = self._request(admin_user)
        admin_obj.send_to_mealie_selected(request, Recipe.objects.filter(pk=recipe.pk))
        messages = [str(m) for m in get_messages(request)]
        assert any("No default Mealie source" in m for m in messages)

    def test_send_to_mealie_selected_success(self, admin_user, recipe, source):
        MealieSource.objects.create(name="M", api_url="https://mealie.example.com", api_token="t", is_default=True)
        admin_obj = self._admin()
        request = self._request(admin_user)
        with patch("cookistash.cookidoo.admin.send_to_mealie.apply") as mock_apply:
            mock_apply.return_value.get.return_value = "task-id"
            admin_obj.send_to_mealie_selected(request, Recipe.objects.filter(pk=recipe.pk))
        messages = [str(m) for m in get_messages(request)]
        assert any("Sent 1 recipe" in m for m in messages)

    def test_send_to_mealie_selected_reports_failures(self, admin_user, recipe, source):
        MealieSource.objects.create(name="M", api_url="https://mealie.example.com", api_token="t", is_default=True)
        admin_obj = self._admin()
        request = self._request(admin_user)
        with patch("cookistash.cookidoo.admin.send_to_mealie.apply", side_effect=RuntimeError("mealie down")):
            admin_obj.send_to_mealie_selected(request, Recipe.objects.filter(pk=recipe.pk))
        messages = [str(m) for m in get_messages(request)]
        assert any("mealie down" in m for m in messages)


@pytest.mark.django_db
class TestScrapeView:
    def test_get_renders_form(self, client, admin_user):
        client.force_login(admin_user)
        resp = client.get(reverse("admin:scrape-recipe"))
        assert resp.status_code == 200
        assert "form" in resp.context

    def test_post_invalid_id_shows_error(self, client, admin_user, source):
        client.force_login(admin_user)
        resp = client.post(reverse("admin:scrape-recipe"), {"recipe_input": "no id here"}, follow=True)
        messages = [str(m) for m in get_messages(resp.wsgi_request)]
        assert any("Couldn't find a recipe ID" in m for m in messages)

    def test_post_no_source_shows_error(self, client, admin_user):
        client.force_login(admin_user)
        resp = client.post(reverse("admin:scrape-recipe"), {"recipe_input": "r123456"}, follow=True)
        messages = [str(m) for m in get_messages(resp.wsgi_request)]
        assert any("No Cookidoo source" in m for m in messages)

    def test_post_valid_dispatches_scrape(self, client, admin_user, source):
        client.force_login(admin_user)
        with patch("cookistash.cookidoo.admin.scrape_recipe.delay") as mock_delay:
            mock_delay.return_value.id = "task-123"
            resp = client.post(reverse("admin:scrape-recipe"), {"recipe_input": "r123456"}, follow=True)
        mock_delay.assert_called_once_with("r123456")
        messages = [str(m) for m in get_messages(resp.wsgi_request)]
        assert any("Scrape started" in m for m in messages)

    def test_post_invalid_form_rerenders(self, client, admin_user):
        client.force_login(admin_user)
        resp = client.post(reverse("admin:scrape-recipe"), {"recipe_input": ""})
        assert resp.status_code == 200
        assert resp.context["form"].is_valid() is False


class TestScrapedRecipeAdmin:
    def _admin(self):
        from cookistash.cookidoo.models import ScrapedRecipe

        return ScrapedRecipeAdmin(ScrapedRecipe, admin_site=None)

    def test_linked_recipe_with_recipe(self, recipe):
        from cookistash.cookidoo.models import ScrapedRecipe

        scrape = ScrapedRecipe.objects.create(recipe=recipe, success=True)
        admin_obj = self._admin()
        html = admin_obj.linked_recipe(scrape)
        assert str(recipe) in html

    def test_linked_recipe_without_recipe(self):
        # ScrapedRecipe.recipe is a required FK in the schema, but the admin
        # method defensively checks truthiness anyway - exercise that branch
        # directly rather than via an invalid DB row.
        admin_obj = self._admin()
        assert admin_obj.linked_recipe(MagicMock(recipe=None)) == "-"

    def test_create_recipe_from_scrape_creates(self, admin_user, recipe):
        from cookistash.cookidoo.models import ScrapedRecipe

        scrape = ScrapedRecipe.objects.create(recipe=recipe, success=True)
        admin_obj = self._admin()
        rf = RequestFactory()
        request = rf.post("/admin/cookidoo/scrapedrecipe/")
        request.user = admin_user
        request.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage

        request._messages = FallbackStorage(request)

        admin_obj.create_recipe_from_scrape(request, ScrapedRecipe.objects.filter(pk=scrape.pk))

        assert MealieRecipe.objects.filter(recipe=recipe).exists()
        messages = [str(m) for m in get_messages(request)]
        assert any("1 created" in m for m in messages)
