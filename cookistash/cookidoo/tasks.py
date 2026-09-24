import hashlib
import json
import logging

from celery import shared_task
from django.utils import timezone
from django_celery_results.models import TaskResult

from .client import CookidooClient
from .models import Recipe, ScrapedRecipe, Source

logger = logging.getLogger(__name__)


def _hash_data(data: dict) -> str:
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@shared_task(bind=True)
def scrape_recipe(self, recipe_id: str):
    # Source is a strict singleton (see cookidoo.Source.save()) - there is
    # only ever one to use. It's fetched here rather than accepted as a
    # parameter because a Django model instance isn't JSON-serializable,
    # which would break a real (non-eager) Celery dispatch.
    source = Source.objects.get()

    recipe, _ = Recipe.objects.get_or_create(
        id=recipe_id,
        defaults={
            "name": recipe_id,
            "url": "",
            "language": "",
            "markets": [],
            "status": "",
            "publication_date": timezone.now(),
            "source": source,
        },
    )
    recipe.scrape_status = "in_progress"
    recipe.save(update_fields=["scrape_status"])

    scrape = ScrapedRecipe(source=source, recipe=recipe)
    try:
        scrape.celery_task, _ = TaskResult.objects.get_or_create(task_id=self.request.id)

        client = CookidooClient(source)
        data, req = client.get_recipe(recipe_id)

        Recipe.objects.filter(pk=recipe.pk).update(
            name=data["title"],
            url=req.url,
            image_url=data["descriptiveAssets"][0]["landscape"].format(transformation="t_web_rdp_recipe_584x480_1_5x"),
            language=data["language"],
            markets=data["markets"],
            status=data["status"],
            publication_date=data["publicationDate"],
            source=source,
            last_scraped_at=timezone.now(),
            scrape_status="success",
            scrape_error=None,
        )

        scrape.url = req.url
        scrape.raw_data = data
        scrape.content_hash = _hash_data(data)
        scrape.success = True

    except Exception as e:
        logger.exception("Scrape failed for recipe %s", recipe_id)
        scrape.success = False
        Recipe.objects.filter(pk=recipe.pk).update(
            scrape_status="failed",
            scrape_error=str(e),
        )
        raise
    finally:
        scrape.save()

    return str(scrape.scrape_id)


@shared_task
def rescrape_recipe(recipe_id: str, sync_to_mealie: bool = False):
    """Force a fresh scrape of an existing recipe.

    If sync_to_mealie is True and the recipe was previously synced, also push
    the refreshed content to Mealie (a no-op if the content hasn't changed).
    """
    result = scrape_recipe.apply(args=(recipe_id,)).get(disable_sync_subtasks=False)
    if sync_to_mealie:
        from cookistash.mealie.models import Recipe as MealieRecipe

        if MealieRecipe.objects.filter(recipe_id=recipe_id).exists():
            send_to_mealie.apply(args=(recipe_id,)).get(disable_sync_subtasks=False)
    return result


@shared_task(bind=True)
def send_to_mealie(self, recipe_id: str, force: bool = False):
    """Transform the latest scrape of a recipe and push it to Mealie.

    Skips the push (and the Mealie API calls it costs) if the latest scrape's
    content hasn't changed since the last successful sync, unless force=True.
    """
    from cookistash.mealie.models import Recipe as MealieRecipe
    from cookistash.mealie.transformer import MealieTransformer

    scrape = ScrapedRecipe.objects.filter(recipe_id=recipe_id, success=True).order_by("-scraped_at").first()
    if scrape is None:
        raise ValueError(f"No successful scrape found for recipe {recipe_id}")

    existing = MealieRecipe.objects.filter(recipe_id=recipe_id).first()
    if not force and existing and scrape.content_hash and existing.synced_hash == scrape.content_hash:
        logger.info("Skipping Mealie sync for %s: content unchanged since last sync", recipe_id)
        return existing.slug

    transformer = MealieTransformer()
    mealie_recipe = transformer.transform(scrape)
    transformer.create_in_mealie(mealie_recipe)

    MealieRecipe.objects.filter(pk=mealie_recipe.pk).update(
        synced_hash=scrape.content_hash,
        last_synced_at=timezone.now(),
    )
    return mealie_recipe.slug


@shared_task
def rescrape_stale_recipes(days_old: int = 7):
    """Re-scrape recipes that haven't been scraped in `days_old` days (or never)."""
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(days=days_old)
    stale = Recipe.objects.filter(last_scraped_at__lt=cutoff) | Recipe.objects.filter(last_scraped_at__isnull=True)
    for recipe in stale.distinct():
        rescrape_recipe.delay(recipe.id, sync_to_mealie=True)
