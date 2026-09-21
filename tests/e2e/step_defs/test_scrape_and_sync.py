import time

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

pytestmark = pytest.mark.e2e

scenarios("../features/scrape_and_sync.feature")


# --- Background -------------------------------------------------------------


@given("a default Cookidoo source is configured")
def _(cookidoo_source):
    return cookidoo_source


@given("a default Mealie source is configured")
def _(mealie_source):
    return mealie_source


# --- Given: recipe already in some state -------------------------------------


@given(parsers.parse('recipe "{recipe_id}" has been scraped'), target_fixture="scraped_recipe_id")
def _(recipe_id, stub_cookidoo_recipe):
    from cookistash.cookidoo.tasks import scrape_recipe

    stub_cookidoo_recipe(recipe_id)
    scrape_recipe.apply(args=(recipe_id,)).get(disable_sync_subtasks=False)
    return recipe_id


@given(
    parsers.parse('recipe "{recipe_id}" has been scraped and sent to Mealie once'),
    target_fixture="scraped_recipe_id",
)
def _(recipe_id, stub_cookidoo_recipe):
    from cookistash.cookidoo.tasks import scrape_recipe, send_to_mealie

    stub_cookidoo_recipe(recipe_id)
    scrape_recipe.apply(args=(recipe_id,)).get(disable_sync_subtasks=False)
    send_to_mealie.apply(args=(recipe_id,), kwargs={"force": True}).get(disable_sync_subtasks=False)
    return recipe_id


# --- When ---------------------------------------------------------------------


@when(parsers.parse('I scrape recipe "{recipe_id}"'), target_fixture="scraped_recipe_id")
def _(recipe_id, stub_cookidoo_recipe):
    from cookistash.cookidoo.tasks import scrape_recipe

    stub_cookidoo_recipe(recipe_id)
    scrape_recipe.apply(args=(recipe_id,)).get(disable_sync_subtasks=False)
    return recipe_id


@when(parsers.parse('I send recipe "{recipe_id}" to Mealie'), target_fixture="mealie_slug")
def _(recipe_id):
    from cookistash.cookidoo.tasks import send_to_mealie
    from cookistash.mealie.models import Recipe as MealieRecipe

    send_to_mealie.apply(args=(recipe_id,), kwargs={"force": True}).get(disable_sync_subtasks=False)
    # The task returns our local slug (the Cookidoo id) - Mealie's own
    # routing slug (what its API actually addresses the recipe by) is
    # tracked separately, since Mealie always derives its own from the name.
    return MealieRecipe.objects.get(recipe_id=recipe_id).mealie_slug


@when('I send recipe "r96596" to Mealie again without any changes', target_fixture="sync_log")
def _(scraped_recipe_id, caplog):
    from cookistash.cookidoo.tasks import send_to_mealie

    with caplog.at_level("INFO"):
        send_to_mealie.apply(args=(scraped_recipe_id,)).get(disable_sync_subtasks=False)
    return caplog.text


@when("the recipe is scraped again", target_fixture="rescrape_timestamp")
def _(scraped_recipe_id, stub_cookidoo_recipe):
    from cookistash.cookidoo.models import Recipe
    from cookistash.cookidoo.tasks import scrape_recipe

    before = Recipe.objects.get(id=scraped_recipe_id).last_scraped_at
    time.sleep(0.01)  # ensure a measurable timestamp difference
    stub_cookidoo_recipe(scraped_recipe_id)
    scrape_recipe.apply(args=(scraped_recipe_id,)).get(disable_sync_subtasks=False)
    return before


# --- Then -----------------------------------------------------------------


@then("the recipe is stored with a successful scrape status")
def _(scraped_recipe_id):
    from cookistash.cookidoo.models import Recipe

    recipe = Recipe.objects.get(id=scraped_recipe_id)
    assert recipe.scrape_status == "success"


@then(parsers.parse('the recipe name is "{name}"'))
def _(scraped_recipe_id, name):
    from cookistash.cookidoo.models import Recipe

    recipe = Recipe.objects.get(id=scraped_recipe_id)
    assert recipe.name == name


@then("the recipe exists in Mealie")
def _(mealie_slug, mealie_source):
    import requests

    resp = requests.get(
        f"{mealie_source.api_url}/api/recipes/{mealie_slug}",
        headers={"Authorization": f"Bearer {mealie_source.api_token}"},
        timeout=10,
    )
    assert resp.status_code == 200


@then(parsers.parse("the Mealie recipe has {count:d} ingredients"))
def _(mealie_slug, mealie_source, count):
    recipe = _fetch_mealie_recipe(mealie_source, mealie_slug)
    assert len(recipe["recipeIngredient"]) == count


@then(parsers.parse("the Mealie recipe has {count:d} instructions"))
def _(mealie_slug, mealie_source, count):
    recipe = _fetch_mealie_recipe(mealie_source, mealie_slug)
    assert len(recipe["recipeInstructions"]) == count


@then(parsers.parse('the Mealie recipe has an ingredient with food "{food}" and unit "{unit}"'))
def _(mealie_slug, mealie_source, food, unit):
    recipe = _fetch_mealie_recipe(mealie_source, mealie_slug)
    matches = [
        ing
        for ing in recipe["recipeIngredient"]
        if (ing.get("food") or {}).get("name") == food and (ing.get("unit") or {}).get("name") == unit
    ]
    assert matches, f"No ingredient with food={food!r} unit={unit!r} in {recipe['recipeIngredient']}"


@then(parsers.parse('the Mealie recipe\'s nutrition "{field}" is "{value}"'))
def _(mealie_slug, mealie_source, field, value):
    recipe = _fetch_mealie_recipe(mealie_source, mealie_slug)
    assert recipe["nutrition"][field] == value


@then("the sync is skipped because the content is unchanged")
def _(sync_log):
    assert "content unchanged since last sync" in sync_log


@then("the recipe's last scraped time is updated")
def _(scraped_recipe_id, rescrape_timestamp):
    from cookistash.cookidoo.models import Recipe

    recipe = Recipe.objects.get(id=scraped_recipe_id)
    assert recipe.last_scraped_at > rescrape_timestamp


@then("a new scrape record exists for the recipe")
def _(scraped_recipe_id):
    from cookistash.cookidoo.models import ScrapedRecipe

    assert ScrapedRecipe.objects.filter(recipe_id=scraped_recipe_id).count() >= 2


def _fetch_mealie_recipe(mealie_source, slug):
    import requests

    resp = requests.get(
        f"{mealie_source.api_url}/api/recipes/{slug}",
        headers={"Authorization": f"Bearer {mealie_source.api_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
