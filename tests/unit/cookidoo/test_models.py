from datetime import datetime

import pytest

from cookistash.cookidoo.models import Recipe, ScrapedRecipe, Source

pytestmark = pytest.mark.django_db


class TestSource:
    def test_create_source(self):
        source = Source.objects.create(name="Test Source", url="https://example.com", locale="en-GB", is_default=True)
        assert source.pk is not None
        assert str(source) == "Test Source"
        assert source.is_default is True

    def test_only_one_default_with_three_sources(self):
        s1 = Source.objects.create(name="Source 1", locale="en-GB", is_default=True)
        assert s1.is_default is True

        s2 = Source.objects.create(name="Source 2", locale="en-GB", is_default=True)
        s1.refresh_from_db()
        assert s1.is_default is False
        assert s2.is_default is True

        s3 = Source.objects.create(name="Source 3", locale="en-GB", is_default=True)
        s1.refresh_from_db()
        s2.refresh_from_db()
        assert s1.is_default is False
        assert s2.is_default is False
        assert s3.is_default is True

    @pytest.mark.parametrize("name, is_default", [("s1", False), ("s2", True)])
    def test_auto_default_if_none(self, name, is_default):
        source = Source.objects.create(name=name, url="https://example.com", is_default=is_default)
        assert source.pk is not None
        assert str(source) == name
        assert source.is_default is True


class TestRecipe:
    def test_create_recipe(self):
        source = Source.objects.create(name="S", locale="en-GB")
        recipe = Recipe.objects.create(
            id="r123",
            name="Gazpacho",
            language="en",
            markets=["uk", "pt"],
            status="ok",
            publication_date=datetime.now(),
            source=source,
        )
        assert recipe.pk == "r123"
        assert str(recipe) == "Gazpacho (r123)"
        assert recipe.source == source

    def test_id_must_start_with_r(self):
        from django.core.exceptions import ValidationError

        recipe = Recipe(
            id="x123", name="Invalid", language="en", markets=[], status="ok", publication_date=datetime.now()
        )
        with pytest.raises(ValidationError):
            recipe.full_clean()


@pytest.mark.django_db
class TestScrapedRecipe:
    def test_create_scraped_recipe(self):
        source = Source.objects.create(name="S", locale="en-GB")
        recipe = Recipe.objects.create(
            id="r123",
            name="Gazpacho",
            language="en",
            markets=["uk"],
            status="ok",
            publication_date=datetime.now(),
            source=source,
        )
        scraped = ScrapedRecipe.objects.create(recipe=recipe, source=source, success=True)
        assert scraped.pk is not None
        assert str(scraped) == f"{scraped.scrape_id} ({recipe.id})"
        assert scraped.success is True
