from django.contrib import admin
from unfold.admin import ModelAdmin

from cookistash.mealie.models import Food, Ingredient, Recipe, Source, Unit


@admin.register(Source)
class SourceAdmin(ModelAdmin):
    def has_add_permission(self, request):
        # Singleton - normally bootstrapped from MEALIE_API_URL/
        # MEALIE_API_TOKEN, see mealie.Source.save().
        return not Source.objects.exists()


@admin.register(Food)
class FoodAdmin(ModelAdmin): ...


@admin.register(Unit)
class UnitAdmin(ModelAdmin): ...


@admin.register(Ingredient)
class IngredientAdmin(ModelAdmin): ...


@admin.register(Recipe)
class RecipeAdmin(ModelAdmin):
    list_display = ["scraped_recipe__recipe__name", "scraped_recipe__recipe_id"]
