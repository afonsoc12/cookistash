from datetime import datetime

import pytest
from django.core.exceptions import ValidationError

from cookistash.cookidoo.models import Recipe, ScrapedRecipe, Source

pytestmark = pytest.mark.django_db


class TestSource:
    def test_create_source(self):
        source = Source.objects.create(name="Test Source", url="https://example.com", locale="en-GB")
        assert source.pk is not None
        assert str(source) == "Test Source"

    def test_country_derived_from_locale(self):
        source = Source.objects.create(name="S", url="https://cookidoo.pt", locale="pt-PT")
        assert source.country == "pt"

    def test_second_source_rejected(self):
        Source.objects.create(name="Source 1", url="https://example.com", locale="en-GB")
        with pytest.raises(ValidationError):
            Source.objects.create(name="Source 2", url="https://example.com", locale="pt-PT")

    def test_existing_source_can_be_updated(self):
        source = Source.objects.create(name="Source 1", url="https://example.com", locale="en-GB")
        source.locale = "pt-PT"
        source.save()
        source.refresh_from_db()
        assert source.locale == "pt-PT"


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
