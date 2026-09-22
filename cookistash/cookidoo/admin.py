from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group, User
from django.db.models import JSONField
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.safestring import mark_safe
from django_celery_beat.admin import (
    ClockedScheduleAdmin,
    CrontabScheduleAdmin,
    IntervalScheduleAdmin,
    PeriodicTaskAdmin,
    SolarScheduleAdmin,
)
from django_celery_beat.models import (
    ClockedSchedule,
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
    SolarSchedule,
)
from django_celery_results.models import GroupResult, TaskResult
from django_json_widget.widgets import JSONEditorWidget
from unfold.admin import ModelAdmin, TabularInline
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from cookistash.utils import friendly_error, parse_recipe_id

from ..mealie.models import Recipe as MealieRecipe
from ..mealie.models import Source as MealieSource
from .models import Recipe, ScrapedRecipe, Source
from .tasks import scrape_recipe, send_to_mealie

# Unfold only re-themes ModelAdmin subclasses that actually inherit from it -
# django.contrib.auth's default User/Group admin ships as plain
# admin.ModelAdmin, so it renders unstyled unless re-registered like this.
admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UnfoldUserAdmin(UserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm


@admin.register(Group)
class UnfoldGroupAdmin(GroupAdmin, ModelAdmin):
    pass


# --- django_celery_results: same unstyled-admin problem, plus its default
# list view gives no way to tell which Recipe a task belongs to. ---
admin.site.unregister(TaskResult)
admin.site.unregister(GroupResult)


@admin.register(TaskResult)
class UnfoldTaskResultAdmin(ModelAdmin):
    date_hierarchy = "date_done"
    list_display = ["short_task_name", "status_pill", "recipe_link", "date_done", "worker"]
    list_filter = ["status", "task_name", "worker"]
    search_fields = ["task_name", "task_id", "status", "task_args", "task_kwargs"]

    def has_change_permission(self, request, obj=None):
        # Task results are historical records - viewing only, never editable.
        return False

    @admin.display(description="Task")
    def short_task_name(self, obj):
        return (obj.task_name or "").rsplit(".", 1)[-1]

    @admin.display(description="Status")
    def status_pill(self, obj):
        colors = {
            "SUCCESS": "#1b7d4f",
            "FAILURE": "#c0392b",
            "STARTED": "#a06b00",
            "PENDING": "#837a70",
            "RETRY": "#a06b00",
        }
        color = colors.get(obj.status, "#837a70")
        return mark_safe(f'<span style="color:{color};font-weight:700;">{obj.status}</span>')

    @admin.display(description="Recipe")
    def recipe_link(self, obj):
        recipe_id = self._extract_recipe_id(obj)
        if not recipe_id:
            return "-"
        url = reverse("cookidoo:recipe_detail", args=[recipe_id])
        return mark_safe(f'<a href="{url}">{recipe_id}</a>')

    def _extract_recipe_id(self, obj):
        import ast
        import json as _json

        for raw in (obj.task_args, obj.task_kwargs):
            if not raw:
                continue
            # Best-effort display helper only (not correctness-critical) - a
            # single broad except keeps this immune to a ruff-format bug
            # (0.15.2) that mangles multi-exception except-tuples into
            # invalid syntax, and any parse failure here just means no link.
            try:
                parsed = _json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            # Celery stores args/kwargs as the repr() of the Python tuple/dict,
            # JSON-encoded on top of that - e.g. '"(\'r96596\',)"' - so a
            # plain json.loads() only unwraps the outer layer, leaving a
            # string that still needs literal_eval to become real values.
            if isinstance(parsed, str):
                try:
                    parsed = ast.literal_eval(parsed)
                except Exception:  # noqa: BLE001
                    continue
            values = parsed.values() if isinstance(parsed, dict) else parsed
            for v in values:
                if isinstance(v, str) and parse_recipe_id(v):
                    return parse_recipe_id(v)
        return None


@admin.register(GroupResult)
class UnfoldGroupResultAdmin(ModelAdmin):
    date_hierarchy = "date_done"
    list_display = ["group_id", "date_done"]
    list_filter = ["date_done"]
    readonly_fields = ["date_created", "date_done", "result"]
    search_fields = ["group_id"]


# --- django_celery_beat: scheduled task management. Re-register with Unfold
# styling while keeping its own admin logic (custom schedule widgets etc). ---
for _model in (PeriodicTask, ClockedSchedule, CrontabSchedule, SolarSchedule, IntervalSchedule):
    admin.site.unregister(_model)


@admin.register(PeriodicTask)
class UnfoldPeriodicTaskAdmin(PeriodicTaskAdmin, ModelAdmin):
    pass


@admin.register(ClockedSchedule)
class UnfoldClockedScheduleAdmin(ClockedScheduleAdmin, ModelAdmin):
    pass


@admin.register(CrontabSchedule)
class UnfoldCrontabScheduleAdmin(CrontabScheduleAdmin, ModelAdmin):
    pass


@admin.register(SolarSchedule)
class UnfoldSolarScheduleAdmin(SolarScheduleAdmin, ModelAdmin):
    pass


@admin.register(IntervalSchedule)
class UnfoldIntervalScheduleAdmin(IntervalScheduleAdmin, ModelAdmin):
    pass


@admin.register(Source)
class Sources(ModelAdmin):
    list_display = ["name", "url", "locale"]

    def has_add_permission(self, request):
        # Singleton - normally bootstrapped from COOKIDOO_EXPLORE_URL, see
        # cookidoo.Source.save().
        return not Source.objects.exists()


class ScrapedRecipeInline(TabularInline):
    model = ScrapedRecipe
    extra = 0
    max_num = 5
    readonly_fields = (
        "scrape_id_link",
        "scraped_at",
    )
    fields = (
        "scrape_id_link",
        "scraped_at",
    )
    ordering = ("-scraped_at",)

    @admin.display(description="Scrape ID")
    def scrape_id_link(self, obj):
        url = reverse("admin:cookidoo_scrapedrecipe_change", args=[obj.pk])
        return mark_safe(f'<a href="{url}">{obj}</a>')


class RecipeInputForm(forms.Form):
    recipe_input = forms.CharField(
        label="Recipe ID or URL",
        help_text="Enter a Cookidoo recipe ID (e.g. r123456) or full URL.",
        widget=forms.TextInput(attrs={"placeholder": "r123456 or https://cookidoo.xx/recipes/r123456"}),
    )


@admin.register(Recipe)
class RecipeAdmin(ModelAdmin):
    list_display = ["thumbnail", "name", "id", "language", "scrape_status", "last_scraped_at", "mealie_sync_status"]
    list_filter = ["scrape_status"]
    inlines = [ScrapedRecipeInline]
    change_list_template = "admin/recipe_changelist.html"  # add custom button
    actions = ["rescrape_selected", "send_to_mealie_selected"]

    @admin.display(description="Recipe Image")
    def thumbnail(self, obj):
        if obj.image_url:
            return mark_safe(f'<img src="{obj.image_url}" width="100" />')
        return "-"

    @admin.display(description="Mealie")
    def mealie_sync_status(self, obj):
        mealie_recipe = MealieRecipe.objects.filter(recipe=obj).first()
        if not mealie_recipe or not mealie_recipe.mealie_slug:
            return "not synced"
        source = MealieSource.objects.filter(is_default=True).first()
        if not source:
            return f"synced ({mealie_recipe.mealie_slug})"
        url = source.recipe_url(mealie_recipe.mealie_slug)
        return mark_safe(f'<a href="{url}" target="_blank">synced ({mealie_recipe.mealie_slug})</a>')

    @admin.action(description="Re-scrape selected recipes")
    def rescrape_selected(self, request, queryset):
        if not Source.objects.exists():
            self.message_user(request, "No Cookidoo source configured.", level=messages.ERROR)
            return
        ok, failed = 0, []
        for recipe in queryset:
            try:
                scrape_recipe.apply(args=(recipe.id,)).get(disable_sync_subtasks=False)
                ok += 1
            except Exception as e:
                failed.append(f"{recipe.id}: {friendly_error('Re-scrape', e)}")
        if ok:
            self.message_user(request, f"Re-scraped {ok} recipe(s).", level=messages.SUCCESS)
        for msg in failed:
            self.message_user(request, msg, level=messages.ERROR)

    @admin.action(description="Send selected recipes to Mealie")
    def send_to_mealie_selected(self, request, queryset):
        if not MealieSource.objects.filter(is_default=True).exists():
            self.message_user(request, "No default Mealie source configured.", level=messages.ERROR)
            return
        ok, failed = 0, []
        for recipe in queryset:
            try:
                send_to_mealie.apply(args=(recipe.id,), kwargs={"force": True}).get(disable_sync_subtasks=False)
                ok += 1
            except Exception as e:
                failed.append(f"{recipe.id}: {friendly_error('Send to Mealie', e)}")
        if ok:
            self.message_user(request, f"Sent {ok} recipe(s) to Mealie.", level=messages.SUCCESS)
        for msg in failed:
            self.message_user(request, msg, level=messages.ERROR)

    # Add custom URL to handle scrape form
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("scrape/", self.admin_site.admin_view(self.scrape_view), name="scrape-recipe"),
        ]
        return custom_urls + urls

    def scrape_view(self, request):
        if request.method == "POST":
            form = RecipeInputForm(request.POST)
            if form.is_valid():
                recipe_input = form.cleaned_data["recipe_input"]
                recipe_id = parse_recipe_id(recipe_input)
                if not recipe_id:
                    messages.error(request, f"Couldn't find a recipe ID (e.g. r123456) in '{recipe_input}'.")
                elif not Source.objects.exists():
                    messages.error(request, "No Cookidoo source is configured. Create one first.")
                else:
                    task = scrape_recipe.delay(recipe_id)
                    messages.info(request, f"Scrape started for '{recipe_input}' (task id: {task.id})")
                return redirect("..")
        else:
            form = RecipeInputForm()

        return render(
            request,
            "admin/scrape_form.html",
            {"form": form, "title": "Scrape New Recipe", "opts": self.model._meta},
        )


@admin.register(ScrapedRecipe)
class ScrapedRecipeAdmin(ModelAdmin):
    list_display = ["scrape_id", "linked_recipe", "source", "success", "scraped_at"]
    list_display_links = ("scrape_id", "linked_recipe")
    fields = ["scrape_id", "recipe", "source", "success", "celery_task", "scraped_at", "raw_data"]
    readonly_fields = ["scrape_id", "recipe", "source", "success", "celery_task", "scraped_at"]
    ordering = ("-scraped_at",)
    formfield_overrides = {JSONField: {"widget": JSONEditorWidget}}

    @admin.display(description="Recipe")
    def linked_recipe(self, obj):
        if not obj.recipe:
            return "-"
        url = reverse("admin:cookidoo_recipe_change", args=[obj.recipe.id])
        return mark_safe(f'<a href="{url}">{obj.recipe}</a>')

    actions = ["create_recipe_from_scrape"]

    @admin.action(description="Create Mealie Recipe from ScrappedRecipe")
    def create_recipe_from_scrape(self, request, queryset):
        """
        Create Recipe objects from selected ScrappedRecipe entries,
        resolving the category foreign key.
        """
        created_ct = 0
        updated_ct = 0
        for scrape in queryset:
            recipe, created = MealieRecipe.objects.update_or_create(
                recipe=scrape.recipe, defaults={"scraped_recipe": scrape}
            )

            created_ct += created
            updated_ct += not created

        self.message_user(request, f"{created_ct} created, {updated_ct} updated successfully!")
