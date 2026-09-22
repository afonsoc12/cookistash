from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django_celery_results.models import TaskResult


class Source(models.Model):
    """Cookidoo has one domain per market (cookidoo.pt, cookidoo.co.uk,
    cookidoo.thermomix.com, ...) with no cross-market API, so unlike Mealie
    there's no sense in supporting more than one of these at once - a
    single row is enforced in save() below. It's normally bootstrapped from
    the COOKIDOO_EXPLORE_URL env var (see management command
    sync_cookidoo_source), not hand-entered in admin.
    """

    name = models.CharField(max_length=100)
    url = models.URLField()
    locale = models.CharField(max_length=5)
    headers = models.JSONField(default=dict, blank=True, null=True)

    def __str__(self):
        return f"{self.name}"

    @property
    def country(self) -> str:
        """Lowercase market code derived from the locale, e.g. "pt-PT" -> "pt"."""
        return self.locale.split("-")[-1].lower()

    def save(self, *args, **kwargs):
        if self.pk is None and Source.objects.exists():
            raise ValidationError(
                "Only one Cookidoo Source is supported (each market is a separate domain/API) - "
                "edit the existing one instead of creating a new one."
            )
        super().save(*args, **kwargs)


class Recipe(models.Model):
    SCRAPE_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    id = models.CharField(
        primary_key=True, max_length=10, validators=[RegexValidator(r"^r", message="Must start with 'r'")]
    )
    name = models.CharField(max_length=100)
    url = models.URLField()
    image_url = models.URLField(blank=True, null=True)
    language = models.CharField(max_length=2)
    markets = models.JSONField()
    status = models.CharField(max_length=10)
    publication_date = models.DateTimeField()
    source = models.ForeignKey(Source, editable=False, on_delete=models.SET_NULL, null=True)

    last_scraped_at = models.DateTimeField(null=True, blank=True)
    scrape_status = models.CharField(max_length=15, choices=SCRAPE_STATUS_CHOICES, default="pending")
    scrape_error = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.id})"


class ScrapedRecipe(models.Model):
    """
    Represents a single scrape of a recipe from a source (Cookidoo, etc.)
    """

    scrape_id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE)
    source = models.ForeignKey(Source, editable=False, on_delete=models.SET_NULL, null=True)
    url = models.URLField()
    success = models.BooleanField()
    raw_data = models.JSONField(default=dict)
    content_hash = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        editable=False,
        help_text="SHA-256 of raw_data, used to detect no-op rescrapes",
    )
    scraped_at = models.DateTimeField(auto_now_add=True)
    celery_task = models.ForeignKey(
        TaskResult,
        on_delete=models.SET_NULL,
        null=True,
        editable=False,
        help_text="Celery task associated with this scrape",
    )

    class Meta:
        ordering = ["-scraped_at"]

    def __str__(self):
        return f"{self.scrape_id} ({self.recipe.id})"
