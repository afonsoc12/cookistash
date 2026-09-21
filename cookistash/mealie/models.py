import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from django.db import models

from cookistash.cookidoo.models import Recipe as CookidooRecipe
from cookistash.cookidoo.models import ScrapedRecipe
from cookistash.utils import camel_to_snake, snake_to_camel


class ModelMealieApi(models.Model):
    class Meta:
        abstract = True

    @classmethod
    def get_or_create_from_api_data(cls, data: dict):
        """
        Create or get a Food object from API data dict.
        - Converts camelCase keys to snake_case.
        - Uses 'id' as the lookup field.
        - Filters only valid model fields.
        """

        # Convert keys to snake_case
        snake_data = {camel_to_snake(k): v for k, v in data.items()}

        # Keep only valid model fields
        valid_fields = {f.name for f in cls._meta.get_fields()}

        defaults = {k: v for k, v in snake_data.items() if k in valid_fields}

        # Get or create. django-stubs can't resolve `.objects` on an abstract
        # base referenced generically via `cls` - it's only attached to
        # concrete subclasses at runtime, which is exactly how this is used.
        obj = cls.objects.filter(name=data["name"]).first()  # type: ignore[attr-defined]
        if obj:
            return obj, False
        else:
            return cls.objects.create(**defaults), True  # type: ignore[attr-defined]

    def to_api_data(self, exclude=None):
        """
        Convert this model instance into an API-style dict:
        - Converts snake_case to camelCase.
        - Serializes UUID, Decimal, FK, M2M.
        - Excludes fields from external modules or in `exclude`.
        """
        if exclude is None:
            exclude = []

        class DjangoSerializer(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, UUID):
                    return str(obj)
                if isinstance(obj, Decimal):
                    return float(obj)
                if isinstance(obj, (datetime, date)):
                    return obj.isoformat()
                return super().default(obj)

        current_module = self.__class__.__module__
        data: dict[str, Any] = {}

        for field in self._meta.get_fields():
            # --- Exclusions ---
            if field.name in exclude:
                continue
            # Skip reverse or proxy relations from other modules
            if hasattr(field, "model") and field.model.__module__ != current_module:
                continue
            # Skip reverse relations (auto-created)
            if field.auto_created and not field.concrete:
                continue

            field_name = snake_to_camel(field.name)
            value = getattr(self, field.name, None)

            if value is None:
                continue

            # --- Handle types ---
            if field.many_to_many:
                related_objects = getattr(self, field.name).all()
                data[field_name] = [
                    obj.to_api_data() if hasattr(obj, "to_api_data") else obj.pk for obj in related_objects
                ]

            elif field.is_relation and not field.many_to_many:
                related_obj = value
                if related_obj is None:
                    data[field_name] = None
                elif hasattr(related_obj, "to_api_data"):
                    # Avoid recursion on same class
                    if related_obj.__class__ == self.__class__:
                        data[field_name] = related_obj.pk
                    else:
                        data[field_name] = related_obj.to_api_data()
                else:
                    data[field_name] = related_obj.pk

            elif field.concrete:
                data[field_name] = value

        return json.loads(json.dumps(data, cls=DjangoSerializer))


class Source(models.Model):
    name = models.CharField(max_length=100)
    api_url = models.URLField(help_text="Server-to-server API URL, e.g. http://mealie:9000 on the docker network.")
    public_url = models.URLField(
        blank=True,
        null=True,
        help_text="Browser-facing URL, e.g. http://localhost:9000. Falls back to api_url if blank.",
    )
    group_slug = models.CharField(
        max_length=100, default="home", help_text="Mealie group slug used to build recipe links, e.g. 'home'."
    )
    api_token = models.CharField(max_length=350)
    headers = models.JSONField(default=dict, blank=True, null=True)
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name}"

    def recipe_url(self, slug: str) -> str:
        base = (self.public_url or self.api_url).rstrip("/")
        return f"{base}/g/{self.group_slug}/r/{slug}"

    def save(self, *args, **kwargs):
        if self.is_default:
            # clear any existing default
            Source.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        # Auto-default the first source created, so the app is usable
        # without a manual "mark as default" step.
        elif not Source.objects.filter(is_default=True).exists():
            self.is_default = True
        super().save(*args, **kwargs)


class CookidooRefLookupMixin(models.Model):
    """Cookidoo assigns every food/unit a stable reference id, but its own
    display text for that same ref varies a lot between recipes - "c. chá de"
    vs "colher de chá", "Sal" vs "sal", "cebola" vs "cebolas". Matching by
    name alone (~14% of refs in a sample had >1 distinct name) fragments what
    should be one Food/Unit into several near-duplicates. Look up by ref
    first; only fall back to name matching when Cookidoo didn't give us one.
    """

    class Meta:
        abstract = True

    @classmethod
    def get_or_create_by_ref(cls, cookidoo_ref, name):
        # See the ModelMealieApi note above - same abstract-base/`.objects`
        # limitation in django-stubs.
        if cookidoo_ref:
            obj = cls.objects.filter(cookidoo_ref=cookidoo_ref).first()  # type: ignore[attr-defined]
            if obj:
                return obj, False
            return cls.objects.create(cookidoo_ref=cookidoo_ref, name=name), True  # type: ignore[attr-defined]
        return cls.objects.get_or_create(name=name)  # type: ignore[attr-defined]

    def to_api_data(self, exclude=None):
        # Mealie always assigns its own server-side id on create and never
        # honors a client-supplied one (verified directly against a live
        # instance) - trying to force our local id to match it via
        # reconciliation caused split-brain duplicate rows when a food/unit
        # had been synced once before the id diverged. So: local id is
        # purely a local identifier now (like Recipe.mealie_slug's
        # relationship to our own slug), and mealie_id (set once we learn it
        # from a create/lookup response) is what actually gets sent to
        # Mealie's API as "id" - never our own.
        #
        # The ignores below exist because mypy can't see the cooperative-
        # inheritance guarantee that to_api_data/mealie_id are only ever
        # accessed once this mixin is combined with ModelMealieApi and the
        # concrete Food/Unit models (see below) - not from the mixin alone.
        exclude = list(exclude or []) + ["cookidoo_ref", "mealie_id"]
        data = super().to_api_data(exclude=exclude)  # type: ignore[misc]
        if self.mealie_id:  # type: ignore[attr-defined]
            data["id"] = str(self.mealie_id)  # type: ignore[attr-defined]
        else:
            data.pop("id", None)
        return data


class Food(CookidooRefLookupMixin, ModelMealieApi):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    mealie_id = models.UUIDField(blank=True, null=True, editable=False)
    # Same display name can legitimately refer to different Cookidoo
    # ingredients (e.g. two distinct "alho" entries in their taxonomy), so
    # this can't be unique - cookidoo_ref is the real identity when present.
    name = models.CharField(max_length=100)
    cookidoo_ref = models.CharField(max_length=255, blank=True, null=True, unique=True, editable=False)
    plural_name = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    label_id = models.UUIDField(blank=True, null=True)

    def __str__(self):
        return f"{self.name}"


class Unit(CookidooRefLookupMixin, ModelMealieApi):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    mealie_id = models.UUIDField(blank=True, null=True, editable=False)
    name = models.CharField(max_length=50)
    cookidoo_ref = models.CharField(max_length=255, blank=True, null=True, unique=True, editable=False)
    plural_name = models.CharField(max_length=50, null=True)
    abbreviation = models.CharField(max_length=20, blank=True, null=True)
    plural_abbreviation = models.CharField(max_length=20, blank=True, null=True)
    use_abbreviation = models.BooleanField(default=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.name}"


class Ingredient(ModelMealieApi):
    reference_id = models.UUIDField(primary_key=True, editable=False)
    quantity = models.FloatField(null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.RESTRICT, null=True, blank=True)
    food = models.ForeignKey(Food, on_delete=models.RESTRICT, null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    display = models.CharField(max_length=200, blank=True, null=True)
    title = models.CharField(max_length=100, blank=True, null=True)
    original_text = models.TextField(blank=True, null=True)

    def __str__(self):
        unit = (self.unit.abbreviation or self.unit.name) if self.unit else ""
        note = f" ({self.note})" if self.note else ""
        food_name = self.food.name if self.food else ""
        return f"{self.quantity} {unit} {food_name}{note}"


class Recipe(ModelMealieApi):
    """Normalized Mealie-compatible recipe"""

    id = models.UUIDField(unique=True, null=True, editable=False)
    slug = models.SlugField(primary_key=True, editable=False)
    mealie_slug = models.SlugField(
        blank=True,
        null=True,
        editable=False,
        help_text="Mealie's own slug for this recipe (it always re-derives this from "
        "the display name on write, so it can't be pinned to our slug/id).",
    )

    scraped_recipe = models.OneToOneField(ScrapedRecipe, related_name="scraped_recipe", on_delete=models.CASCADE)
    recipe = models.OneToOneField(CookidooRecipe, on_delete=models.CASCADE)

    synced_hash = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        editable=False,
        help_text="content_hash of the ScrapedRecipe last successfully pushed to Mealie",
    )
    last_synced_at = models.DateTimeField(null=True, blank=True, editable=False)

    # user_id = models.CharField(max_length=255, blank=True, null=True)
    # household_id = models.CharField(max_length=255, blank=True, null=True)
    # group_id = models.CharField(max_length=255, blank=True, null=True)
    name = models.CharField(max_length=255)
    image_url = models.URLField()
    description = models.TextField(blank=True, null=True)
    rating = models.PositiveIntegerField(default=None, null=True, blank=True)
    org_url = models.URLField()

    # Yields
    recipe_servings = models.DecimalField(max_digits=5, decimal_places=1, blank=True, null=True)
    recipe_yield_quantity = models.DecimalField(max_digits=5, decimal_places=1, blank=True, null=True)
    recipe_yield = models.CharField(max_length=255, blank=True, null=True)

    # Times
    total_time = models.CharField(max_length=255, blank=True, null=True)
    prep_time = models.CharField(max_length=255, blank=True, null=True)
    perform_time = models.CharField(max_length=255, blank=True, null=True)  # cook time

    # Dependencies
    nutrition = models.JSONField(default=dict, blank=True)
    recipe_category = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)
    tools = models.JSONField(default=list, blank=True)
    recipe_ingredient = models.ManyToManyField(Ingredient, null=True, blank=True)
    # Real instructions come from the related Instruction model + the
    # explicit payload["recipeInstructions"] build in client.py - this JSON
    # field would only ever duplicate/shadow that, so it was removed.

    # assets = models.JSONField(default=list, blank=True)
    notes = models.JSONField(default=list, blank=True)
    extras = models.JSONField(default=dict, blank=True)
    # comments = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"{self.name} ({self.scraped_recipe.recipe_id})"

    def save(self, *args, **kwargs):
        if not self.slug:
            # Use the Cookidoo recipe id as the Mealie slug (instead of a
            # name-derived slug) so the two systems share one lookup key and
            # the link between them is obvious straight from the DB/URL.
            self.slug = self.recipe_id
        super().save(*args, **kwargs)


class Instruction(ModelMealieApi):
    title = models.CharField(max_length=50, null=True)
    summary = models.CharField(max_length=50, null=True)
    formatted_text = models.TextField()
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE)

    @staticmethod
    def parse_instruction(instruction_text):
        pua_mapping = {
            "\ue003": "🔄",
            "\ue002": "🥄",
        }
        pattern = "[" + "".join(re.escape(char) for char in pua_mapping.keys()) + "]"

        def replace_specific_pua(text):
            return re.sub(pattern, lambda m: pua_mapping[m.group(0)], text)

        return replace_specific_pua(instruction_text)

    def __str__(self):
        return f"([{self.title}] {self.summary}: {self.formatted_text}"
