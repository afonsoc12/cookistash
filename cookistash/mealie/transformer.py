import re
from uuid import uuid4

from cookistash.cookidoo.models import ScrapedRecipe
from cookistash.mealie.client import MealieClient
from cookistash.mealie.models import Food, Ingredient, Instruction, Source, Unit
from cookistash.mealie.models import Recipe as MealieRecipe


def _strip_html(text):
    return re.sub(r"<[^>]+>", "", text).strip()


def _normalise_quantity(quantity):
    if "value" in quantity:
        return quantity["value"]
    if "from" in quantity and "to" in quantity:
        return (quantity["from"] + quantity["to"]) / 2
    raise NotImplementedError(f"Cannot normalise ingredient quantity with keys {quantity.keys()}")


def _format_time(entry):
    minutes = entry["quantity"]["value"] / 60
    comment = entry.get("comment")
    return f"{minutes:g} mins" + (f" {comment}" if comment else "")


def _parse_times(times):
    data_by_type = {item["type"]: item for item in times}
    if set(data_by_type.keys()) != set(("activeTime", "totalTime")):
        raise TypeError(f"Invalid types found: {data_by_type.keys()}")

    total_time_parsed = _format_time(data_by_type["totalTime"])
    prep_time_parsed = _format_time(data_by_type["activeTime"])
    return total_time_parsed, prep_time_parsed


_NUTRITION_KEY_MAP = {
    "kcal": "calories",
    "protein": "proteinContent",
    "carb2": "carbohydrateContent",
    "fat": "fatContent",
    "saturatedFat": "saturatedFatContent",
    "dietaryFibre": "fiberContent",
    "sodium": "sodiumContent",
    "sugar": "sugarContent",
    "cholesterol": "cholesterolContent",
    "transFat": "transFatContent",
    "unsaturatedFat": "unsaturatedFatContent",
}


def _build_nutrition(nutrition_groups):
    # Avoid a multi-exception `except (A, B, C):` here - ruff-format 0.15.2
    # (and 0.16.8, still) mangles that into the invalid-looking-but-still-
    # parses-as-Python-2-style `except A, B, C:` on every format run (see the
    # same note in cookidoo/admin.py). Walking the structure with .get()
    # instead sidesteps the bug rather than fighting the formatter.
    if not nutrition_groups:
        return {}
    recipe_nutritions = nutrition_groups[0].get("recipeNutritions") or []
    if not recipe_nutritions:
        return {}
    entries = recipe_nutritions[0].get("nutritions") or []
    result = {}
    for entry in entries:
        mealie_key = _NUTRITION_KEY_MAP.get(entry["type"])
        if mealie_key:
            result[mealie_key] = str(entry["number"])
    return result


class MealieTransformer:
    def __init__(self):
        self.mealie_client = MealieClient(Source.objects.get())

    def transform(self, scrape: ScrapedRecipe) -> MealieRecipe:
        data = scrape.raw_data

        # Flatten ingredient groups
        ingredient_groups = []
        for group in data["recipeIngredientGroups"]:
            title = group["title"]
            first = True
            for ing in group.get("recipeIngredients", []):
                ingredient_groups.append({"group_title": title if first else None, **ing})
                first = False

        # Cookidoo already gives us quantity/unit/food as clean, separate
        # fields - there's no ambiguity to resolve. We used to run these
        # through Mealie's ingredient NLP parser (meant for free-text
        # recipes) to match them to existing Food/Unit catalog entries, but
        # it regularly mis-segments non-English text with high confidence
        # (e.g. "c. chá de sal" -> unit "cup" (wrong, matched on "c."), food
        # "chá de sal" (unit fragment leaked into the food name)). Building
        # directly from Cookidoo's structured fields avoids that whole class
        # of bug; Food/Unit catalog dedup still happens later, in
        # create_in_mealie / MealieClient.create_food/create_unit, by exact
        # name match against Mealie's own catalog.
        ingredients = []
        for ing in ingredient_groups:
            unit_text = (ing.get("unitNotation") or "").strip()
            u = None
            if unit_text:
                # Dedup by Cookidoo's own stable unit_ref, not the display
                # text - the same unit shows up as e.g. both "c. chá de" and
                # "colher de chá" across recipes.
                u, _ = Unit.get_or_create_by_ref(ing.get("unit_ref"), unit_text)

            f, _ = Food.get_or_create_by_ref(ing.get("ingredient_ref"), ing["ingredientNotation"])

            ingredients.append(
                Ingredient.objects.create(
                    reference_id=uuid4(),
                    quantity=_normalise_quantity(ing["quantity"]),
                    food=f,
                    unit=u,
                    note=(ing.get("preparation") or "").strip(),
                    title=ing["group_title"],
                )
            )

        total_time_parsed, prep_time_parsed = _parse_times(data["times"])
        mealie_recipe, _ = MealieRecipe.objects.update_or_create(
            recipe=scrape.recipe,
            defaults=dict(
                scraped_recipe=scrape,
                name=data["title"],
                image_url=data["descriptiveAssets"][0]["landscape"].format(
                    transformation="t_web_rdp_recipe_584x480_1_5x"
                ),
                # description=
                # rating=
                org_url=scrape.url,
                # Yields
                recipe_servings=data["servingSize"]["quantity"]["value"],
                recipe_yield_quantity=data["servingSize"]["quantity"]["value"],
                recipe_yield=data["servingSize"]["unitNotation"],
                # Times
                total_time=total_time_parsed,
                prep_time=prep_time_parsed,
                # perform_time =
                # Taxonomy
                recipe_category=[{"name": c["title"]} for c in data.get("categories", []) if c.get("title")],
                tags=[{"name": t["name"]} for t in data.get("tags", []) if t.get("name")],
                tools=[
                    {"name": u["utensilNotation"]} for u in data.get("recipeUtensils", []) if u.get("utensilNotation")
                ],
                notes=(
                    ([{"title": "Difficulty", "text": data["difficulty"]}] if data.get("difficulty") else [])
                    + [
                        {"title": "", "text": _strip_html(info["content"])}
                        for info in data.get("additionalInformation", [])
                        if info.get("content")
                    ]
                ),
                nutrition=_build_nutrition(data.get("nutritionGroups")),
                # Cookidoo back-reference, so the Mealie recipe can always be
                # traced back to its source regardless of slug/id changes.
                extras={"cookidooId": scrape.recipe_id, "cookidooUrl": scrape.url},
            ),
        )

        # todo fix recipe ingredients
        mealie_recipe.recipe_ingredient.all().delete()
        mealie_recipe.recipe_ingredient.add(*ingredients)
        mealie_recipe.save()

        # Instructions - replace wholesale so removed/reordered steps don't linger
        Instruction.objects.filter(recipe=mealie_recipe).delete()
        for group in data["recipeStepGroups"]:
            title = group["title"]
            first = True
            for step in group.get("recipeSteps", []):
                Instruction.objects.create(
                    recipe=mealie_recipe,
                    title=title if title and first else None,
                    summary=step["title"] if not (title and title.isnumeric()) else None,
                    formatted_text=Instruction.parse_instruction(step["formattedText"]),
                )
                first = False

        return mealie_recipe

    def create_in_mealie(self, recipe: MealieRecipe):
        # Push each distinct Food/Unit via a fresh query rather than the
        # cached FK on each Ingredient - reconciling one duplicate (see
        # MealieClient._reconcile_duplicate) can delete a local row that an
        # already-loaded Ingredient object still holds a stale FK id for.
        food_ids = recipe.recipe_ingredient.exclude(food=None).values_list("food_id", flat=True).distinct()
        for food in Food.objects.filter(id__in=list(food_ids)):
            self.mealie_client.create_food(food)

        unit_ids = recipe.recipe_ingredient.exclude(unit=None).values_list("unit_id", flat=True).distinct()
        for unit in Unit.objects.filter(id__in=list(unit_ids)):
            self.mealie_client.create_unit(unit)

        self.mealie_client.create_or_update_recipe(recipe)
