from django.contrib import admin
from unfold.admin import ModelAdmin

from cookistash.mealie.models import Food, Ingredient, Recipe, Source, Unit


@admin.register(Source)
class SourceAdmin(ModelAdmin): ...


@admin.register(Food)
class FoodAdmin(ModelAdmin): ...


@admin.register(Unit)
class UnitAdmin(ModelAdmin): ...


@admin.register(Ingredient)
class IngredientAdmin(ModelAdmin): ...


@admin.register(Recipe)
class RecipeAdmin(ModelAdmin):
    list_display = ["scraped_recipe__recipe__name", "scraped_recipe__recipe_id"]
