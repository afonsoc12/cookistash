from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from cookistash.cookidoo.models import Recipe, ScrapedRecipe, Source
from cookistash.cookidoo.tasks import (
    _hash_data,
    rescrape_recipe,
    rescrape_stale_recipes,
    scrape_recipe,
    send_to_mealie,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def source():
    return Source.objects.create(name="S", url="https://example.com", locale="en-GB", is_default=True)


def _fake_recipe_data(recipe_id="r123", title="Gazpacho"):
    return {
        "title": title,
        "language": "en",
        "markets": ["uk"],
        "status": "published",
        "publicationDate": "2020-01-01T00:00:00Z",
        "descriptiveAssets": [{"landscape": "https://img.example.com/{transformation}/img.jpg"}],
    }


class TestHashData:
    def test_deterministic_regardless_of_key_order(self):
        a = _hash_data({"x": 1, "y": 2})
        b = _hash_data({"y": 2, "x": 1})
        assert a == b

    def test_different_data_different_hash(self):
        assert _hash_data({"x": 1}) != _hash_data({"x": 2})


class TestScrapeRecipe:
    def test_success_updates_recipe_and_stores_scrape(self, source):
        data = _fake_recipe_data()
        fake_response = MagicMock(url="https://example.com/recipes/recipe/en-GB/r123")

        with patch("cookistash.cookidoo.tasks.CookidooClient") as MockClient:
            MockClient.return_value.get_recipe.return_value = (data, fake_response)
            result = scrape_recipe.apply(args=("r123", source)).get(disable_sync_subtasks=False)

        recipe = Recipe.objects.get(id="r123")
        assert recipe.name == "Gazpacho"
        assert recipe.scrape_status == "success"
        assert recipe.scrape_error is None
        assert recipe.last_scraped_at is not None

        scrape = ScrapedRecipe.objects.get(scrape_id=result)
        assert scrape.success is True
        assert scrape.raw_data == data
        assert scrape.content_hash == _hash_data(data)
        assert scrape.celery_task is not None

    def test_uses_default_source_when_none_given(self, source):
        data = _fake_recipe_data()
        fake_response = MagicMock(url="https://example.com/x")
        with patch("cookistash.cookidoo.tasks.CookidooClient") as MockClient:
            MockClient.return_value.get_recipe.return_value = (data, fake_response)
            scrape_recipe.apply(args=("r123",)).get(disable_sync_subtasks=False)

        recipe = Recipe.objects.get(id="r123")
        assert recipe.source == source

    def test_failure_marks_recipe_failed_and_reraises(self, source):
        with patch("cookistash.cookidoo.tasks.CookidooClient") as MockClient:
            MockClient.return_value.get_recipe.side_effect = RuntimeError("network broke")
            with pytest.raises(RuntimeError, match="network broke"):
                scrape_recipe.apply(args=("r123", source)).get(disable_sync_subtasks=False)

        recipe = Recipe.objects.get(id="r123")
        assert recipe.scrape_status == "failed"
        assert recipe.scrape_error == "network broke"

        scrape = ScrapedRecipe.objects.get(recipe=recipe)
        assert scrape.success is False


class TestRescrapeRecipe:
    def test_rescrapes_without_mealie_sync(self, source):
        data = _fake_recipe_data()
        fake_response = MagicMock(url="https://example.com/x")
        with patch("cookistash.cookidoo.tasks.CookidooClient") as MockClient:
            MockClient.return_value.get_recipe.return_value = (data, fake_response)
            rescrape_recipe.apply(args=("r123", source, False)).get(disable_sync_subtasks=False)

        assert Recipe.objects.filter(id="r123", scrape_status="success").exists()

    def test_syncs_to_mealie_when_previously_synced(self, source):
        from cookistash.mealie.models import Recipe as MealieRecipe
        from cookistash.mealie.models import Source as MealieSource

        data = _fake_recipe_data()
        fake_response = MagicMock(url="https://example.com/x")
        with patch("cookistash.cookidoo.tasks.CookidooClient") as MockClient:
            MockClient.return_value.get_recipe.return_value = (data, fake_response)
            scrape_recipe.apply(args=("r123", source)).get(disable_sync_subtasks=False)

        recipe = Recipe.objects.get(id="r123")
        scrape = ScrapedRecipe.objects.get(recipe=recipe)
        mealie_source = MealieSource.objects.create(name="M", api_url="https://mealie.example.com", api_token="t")
        MealieRecipe.objects.create(recipe=recipe, scraped_recipe=scrape, name="Gazpacho", image_url="", org_url="")

        with (
            patch("cookistash.cookidoo.tasks.CookidooClient") as MockClient,
            patch("cookistash.cookidoo.tasks.send_to_mealie.apply") as mock_send_apply,
        ):
            MockClient.return_value.get_recipe.return_value = (data, fake_response)
            rescrape_recipe.apply(args=("r123", source, True)).get(disable_sync_subtasks=False)

        mock_send_apply.assert_called_once_with(args=("r123",))
        assert mealie_source  # keep reference alive for clarity

    def test_no_sync_when_never_synced_even_if_requested(self, source):
        data = _fake_recipe_data()
        fake_response = MagicMock(url="https://example.com/x")
        with (
            patch("cookistash.cookidoo.tasks.CookidooClient") as MockClient,
            patch("cookistash.cookidoo.tasks.send_to_mealie.apply") as mock_send_apply,
        ):
            MockClient.return_value.get_recipe.return_value = (data, fake_response)
            rescrape_recipe.apply(args=("r123", source, True)).get(disable_sync_subtasks=False)

        mock_send_apply.assert_not_called()


class TestSendToMealie:
    def _make_scrape(self, source, content_hash="abc123"):
        recipe = Recipe.objects.create(
            id="r123",
            name="Gazpacho",
            language="en",
            markets=[],
            status="ok",
            publication_date=datetime.now(),
            source=source,
        )
        scrape = ScrapedRecipe.objects.create(
            recipe=recipe, source=source, success=True, raw_data={"title": "Gazpacho"}, content_hash=content_hash
        )
        return recipe, scrape

    def test_raises_when_no_successful_scrape(self, source):
        Recipe.objects.create(
            id="r123",
            name="Gazpacho",
            language="en",
            markets=[],
            status="ok",
            publication_date=datetime.now(),
            source=source,
        )
        with pytest.raises(ValueError, match="No successful scrape found"):
            send_to_mealie.apply(args=("r123",)).get(disable_sync_subtasks=False)

    def test_transforms_and_syncs_when_not_previously_synced(self, source):
        recipe, scrape = self._make_scrape(source)
        mock_mealie_recipe = MagicMock(pk=1, slug="r123")

        with patch("cookistash.mealie.transformer.MealieTransformer") as MockTransformer:
            MockTransformer.return_value.transform.return_value = mock_mealie_recipe
            result = send_to_mealie.apply(args=("r123",)).get(disable_sync_subtasks=False)

        MockTransformer.return_value.transform.assert_called_once_with(scrape)
        MockTransformer.return_value.create_in_mealie.assert_called_once_with(mock_mealie_recipe)
        assert result == "r123"

    def test_skips_when_content_hash_unchanged(self, source):
        from cookistash.mealie.models import Recipe as MealieRecipe

        recipe, scrape = self._make_scrape(source, content_hash="samehash")
        mealie_recipe = MealieRecipe.objects.create(
            recipe=recipe,
            scraped_recipe=scrape,
            name="Gazpacho",
            image_url="",
            org_url="",
            synced_hash="samehash",
        )

        with patch("cookistash.mealie.transformer.MealieTransformer") as MockTransformer:
            result = send_to_mealie.apply(args=("r123",)).get(disable_sync_subtasks=False)

        MockTransformer.assert_not_called()
        assert result == mealie_recipe.slug

    def test_force_bypasses_unchanged_hash_skip(self, source):
        from cookistash.mealie.models import Recipe as MealieRecipe

        recipe, scrape = self._make_scrape(source, content_hash="samehash")
        MealieRecipe.objects.create(
            recipe=recipe,
            scraped_recipe=scrape,
            name="Gazpacho",
            image_url="",
            org_url="",
            synced_hash="samehash",
        )
        mock_mealie_recipe = MagicMock(pk=1, slug="r123")

        with patch("cookistash.mealie.transformer.MealieTransformer") as MockTransformer:
            MockTransformer.return_value.transform.return_value = mock_mealie_recipe
            send_to_mealie.apply(args=("r123",), kwargs={"force": True}).get(disable_sync_subtasks=False)

        MockTransformer.return_value.transform.assert_called_once()


class TestRescrapeStaleRecipes:
    def test_dispatches_for_stale_and_never_scraped_recipes(self, source):
        stale = Recipe.objects.create(
            id="r1",
            name="Old",
            language="en",
            markets=[],
            status="ok",
            publication_date=datetime.now(),
            source=source,
            last_scraped_at=timezone.now() - timedelta(days=10),
        )
        never_scraped = Recipe.objects.create(
            id="r2",
            name="Never",
            language="en",
            markets=[],
            status="ok",
            publication_date=datetime.now(),
            source=source,
            last_scraped_at=None,
        )
        Recipe.objects.create(
            id="r3",
            name="Fresh",
            language="en",
            markets=[],
            status="ok",
            publication_date=datetime.now(),
            source=source,
            last_scraped_at=timezone.now(),
        )

        with patch("cookistash.cookidoo.tasks.rescrape_recipe.delay") as mock_delay:
            rescrape_stale_recipes.apply(args=(7,)).get(disable_sync_subtasks=False)

        called_ids = {call.args[0] for call in mock_delay.call_args_list}
        assert called_ids == {stale.id, never_scraped.id}
        for call in mock_delay.call_args_list:
            assert call.kwargs == {"sync_to_mealie": True}

    def test_default_days_old_is_seven(self, source):
        Recipe.objects.create(
            id="r1",
            name="JustUnder",
            language="en",
            markets=[],
            status="ok",
            publication_date=datetime.now(),
            source=source,
            last_scraped_at=timezone.now() - timedelta(days=3),
        )
        with patch("cookistash.cookidoo.tasks.rescrape_recipe.delay") as mock_delay:
            rescrape_stale_recipes.apply().get(disable_sync_subtasks=False)
        mock_delay.assert_not_called()
