import json

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import models
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from cookistash.utils import parse_recipe_id

from .client import CATEGORIES, COUNTRIES, CookidooClient
from .models import Recipe, ScrapedRecipe, Source
from .tasks import scrape_recipe, send_to_mealie

# (label, unit) for each Mealie nutrition key we populate - see
# mealie/transformer.py:_NUTRITION_KEY_MAP for what Cookidoo data maps here.
_NUTRITION_LABELS = {
    "calories": ("Calories", "kcal"),
    "proteinContent": ("Protein", "g"),
    "carbohydrateContent": ("Carbs", "g"),
    "fatContent": ("Fat", "g"),
    "saturatedFatContent": ("Saturated fat", "g"),
    "fiberContent": ("Fiber", "g"),
    "sodiumContent": ("Sodium", "mg"),
    "sugarContent": ("Sugar", "g"),
    "cholesterolContent": ("Cholesterol", "mg"),
    "transFatContent": ("Trans fat", "g"),
    "unsaturatedFatContent": ("Unsaturated fat", "g"),
}


def _format_duration(seconds):
    if not seconds:
        return None
    minutes = round(seconds / 60)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}min"
    if hours:
        return f"{hours}h"
    return f"{minutes} min"


def _nutrition_items(nutrition):
    items = []
    for key, value in (nutrition or {}).items():
        if not value:
            continue
        label, unit = _NUTRITION_LABELS.get(key, (key, ""))
        items.append({"label": label, "value": value, "unit": unit})
    return items


def _recipe_context(recipe, action_error=None):
    from cookistash.mealie.models import Recipe as MealieRecipe
    from cookistash.mealie.models import Source as MealieSource

    latest_scrape = ScrapedRecipe.objects.filter(recipe=recipe).order_by("-scraped_at").first()
    mealie_recipe = MealieRecipe.objects.filter(recipe=recipe).first()
    mealie_recipe_url = None
    if mealie_recipe and mealie_recipe.mealie_slug:
        mealie_source = MealieSource.objects.filter(is_default=True).first()
        if mealie_source:
            mealie_recipe_url = mealie_source.recipe_url(mealie_recipe.mealie_slug)
    return {
        "recipe": recipe,
        "latest_scrape": latest_scrape,
        "mealie_recipe": mealie_recipe,
        "mealie_recipe_url": mealie_recipe_url,
        "action_error": action_error,
    }


def recipe_list(request):
    from cookistash.mealie.models import Source as MealieSource

    query = request.GET.get("q", "").strip()
    recipes = Recipe.objects.all().order_by("-last_scraped_at", "name")
    if query:
        recipes = recipes.filter(name__icontains=query)

    paginator = Paginator(recipes, 25)
    page = paginator.get_page(request.GET.get("page"))

    rows = [_recipe_context(r) for r in page.object_list]

    return render(
        request,
        "cookidoo/recipe_list.html",
        {
            "page": page,
            "rows": rows,
            "query": query,
            "has_cookidoo_source": Source.objects.exists(),
            "has_mealie_source": MealieSource.objects.filter(is_default=True).exists(),
        },
    )


def recipe_detail(request, recipe_id):
    from cookistash.mealie.models import Instruction

    recipe = get_object_or_404(Recipe, id=recipe_id)
    context = _recipe_context(recipe)

    mealie_recipe = context["mealie_recipe"]
    ingredients: models.QuerySet | list = []
    instructions: models.QuerySet | list = []
    if mealie_recipe:
        ingredients = mealie_recipe.recipe_ingredient.select_related("food", "unit").order_by("pk")
        instructions = Instruction.objects.filter(recipe=mealie_recipe).order_by("pk")

    raw_json = (
        json.dumps(context["latest_scrape"].raw_data, indent=2, ensure_ascii=False)
        if context["latest_scrape"]
        else None
    )

    context.update(
        {
            "mealie_recipe_obj": mealie_recipe,
            "ingredients": ingredients,
            "instructions": instructions,
            "raw_json": raw_json,
            "nutrition_items": _nutrition_items(mealie_recipe.nutrition) if mealie_recipe else [],
        }
    )
    return render(request, "cookidoo/recipe_detail.html", context)


def discover(request):
    """POC: browse Cookidoo's own catalog by category and import from there,
    instead of needing a recipe ID/link up front.
    """
    source = Source.objects.first()
    category = request.GET.get("category", "")
    # "country" absent entirely (first visit) defaults to the configured
    # source's own market; an explicit "?country=" (including empty, from
    # picking "All countries") always wins.
    if "country" in request.GET:
        country = request.GET.get("country", "")
    else:
        country = source.country if source else ""
    query = request.GET.get("q", "").strip()
    page = int(request.GET.get("page", 0))

    results = []
    fetch_error = None
    if source:
        try:
            client = CookidooClient(source)
            results = client.search(
                category=category or None, country=country or None, query=query or None, page=page, limit=24
            )
        except Exception as e:
            fetch_error = f"Couldn't fetch from Cookidoo: {e}"

    known_ids = set(Recipe.objects.filter(id__in=[r["id"] for r in results]).values_list("id", flat=True))
    for r in results:
        r["already_scraped"] = r["id"] in known_ids
        r["total_time_display"] = _format_duration(r.get("totalTime"))
        if source:
            r["cookidoo_url"] = f"{source.url}recipes/recipe/{source.locale}/{r['id']}"

    return render(
        request,
        "cookidoo/discover.html",
        {
            "categories": CATEGORIES,
            "countries": COUNTRIES,
            "category": category,
            "country": country,
            "query": query,
            "page": page,
            "results": results,
            "fetch_error": fetch_error,
            "has_cookidoo_source": source is not None,
        },
    )


@require_POST
def discover_import(request, recipe_id):
    """Import one recipe found via Discover, then bounce back to the same page/category."""
    try:
        scrape_recipe.apply(args=(recipe_id,)).get(disable_sync_subtasks=False)
        messages.success(request, f"Scraped {recipe_id}.")
    except Exception as e:
        messages.error(request, f"Scrape of {recipe_id} failed: {e}")

    category = request.POST.get("category", "")
    country = request.POST.get("country", "")
    query = request.POST.get("q", "")
    page = request.POST.get("page", "0")
    return discover(_with_get(request, category=category, country=country, q=query, page=page))


def _with_get(request, **params):
    request.GET = request.GET.copy()
    for k, v in params.items():
        request.GET[k] = v
    return request


@require_POST
def recipe_scrape_new(request):
    raw_input = request.POST.get("recipe_id", "").strip()
    recipe_id = parse_recipe_id(raw_input) if raw_input else None

    if not raw_input:
        pass
    elif not recipe_id:
        messages.error(request, f"Couldn't find a recipe ID (e.g. r123456) in '{raw_input}'.")
    elif not Source.objects.exists():
        messages.error(
            request,
            "No Cookidoo source is configured. Create one in the "
            "Django admin (/admin/cookidoo/source/) before scraping.",
        )
    else:
        try:
            scrape_recipe.apply(args=(recipe_id,)).get(disable_sync_subtasks=False)
            messages.success(request, f"Scraped {recipe_id}.")
        except Exception as e:
            messages.error(request, f"Scrape of {recipe_id} failed: {e}")
    return recipe_list(request)


@require_POST
def recipe_rescrape(request, recipe_id):
    recipe = get_object_or_404(Recipe, id=recipe_id)
    action_error = None
    try:
        scrape_recipe.apply(args=(recipe.id,)).get(disable_sync_subtasks=False)
    except Exception as e:
        action_error = f"Re-scrape failed: {e}"
    recipe.refresh_from_db()
    return render(request, "cookidoo/_recipe_card.html", _recipe_context(recipe, action_error))


@require_POST
def recipe_send_to_mealie(request, recipe_id):
    from cookistash.mealie.models import Source as MealieSource

    recipe = get_object_or_404(Recipe, id=recipe_id)
    action_error = None
    if not MealieSource.objects.filter(is_default=True).exists():
        action_error = "No default Mealie source configured (see /admin/mealie/source/)."
    else:
        try:
            send_to_mealie.apply(args=(recipe.id,), kwargs={"force": True}).get(disable_sync_subtasks=False)
        except Exception as e:
            action_error = f"Send to Mealie failed: {e}"
    return render(request, "cookidoo/_recipe_card.html", _recipe_context(recipe, action_error))
