import logging
from urllib.parse import urljoin

from requests import Session
from requests.exceptions import HTTPError

from cookistash.mealie.models import Food, Recipe, Unit

logger = logging.getLogger(__name__)


class MealieClient(Session):
    DEFAULT_HEADERS = {"Accept": "application/json"}
    API_ENDPOINT = "api/"

    def __init__(self, source):
        super().__init__()
        self.url = source.api_url
        self._api_key = source.api_token
        self.headers.update(self.DEFAULT_HEADERS)
        self.headers.update(source.headers if source.headers else self.DEFAULT_HEADERS)
        self.headers.update({"Authorization": f"Bearer {self._api_key}"})
        self.test()

    def __repr__(self):
        return f"{self.__class__.__name__}('{urljoin(self.url, self.API_ENDPOINT)}')"

    def _request(self, method, endpoint, *args, **kwargs):
        if endpoint.startswith("/") or endpoint.endswith("/"):
            raise ValueError("Endpoint must not start or end with '/'")
        req = super().request(
            method,
            urljoin(urljoin(self.url, self.API_ENDPOINT), endpoint),
            *args,
            **kwargs,
        )
        try:
            req.raise_for_status()
        except HTTPError:
            raise
        return req

    def test(self):
        """Raises if status_code is not 2xx."""
        _ = self._request("GET", "app/about")
        return True

    def parse_response(self, response):
        if response.status_code in (
            200,
            201,
        ):
            return response.json(), response.status_code
        else:
            return None, response.status_code

    def _find_by_name(self, endpoint, name):
        # Case-insensitive: Mealie's own uniqueness constraint on these
        # names is case-insensitive (POSTing "vegetarian" when "Vegetarian"
        # already exists 500s server-side rather than 409ing), so an exact
        # match here would miss the very row that caused the conflict.
        result = self._request("GET", endpoint, params={"search": name})
        for item in result.json().get("items", []):
            if item["name"].casefold() == name.casefold():
                return item
        return None

    def create_food(self, food: Food):
        try:
            result = self._request("POST", "foods", json=food.to_api_data()).json()
        except HTTPError as e:
            if "duplicate key" not in e.response.json()["detail"]["exception"]:
                raise
            result = self._find_by_name("foods", food.name)
        if result and str(food.mealie_id) != result["id"]:
            food.mealie_id = result["id"]
            food.save(update_fields=["mealie_id"])
        return result

    def create_unit(self, unit: Unit):
        try:
            result = self._request("POST", "units", json=unit.to_api_data()).json()
        except HTTPError as e:
            if "duplicate key" not in e.response.json()["detail"]["exception"]:
                raise
            result = self._find_by_name("units", unit.name)
        if result and str(unit.mealie_id) != result["id"]:
            unit.mealie_id = result["id"]
            unit.save(update_fields=["mealie_id"])
        return result

    def create_recipe(self, recipe: Recipe):
        result = self._request("POST", "recipes", json={"name": recipe.name})
        return result.json()

    def get_recipe(self, recipe_slug):
        try:
            result = self._request("GET", f"recipes/{recipe_slug}")
        except HTTPError as e:
            if e.response.status_code == 404 and e.response.json()["detail"]["message"] == "No Entry Found":
                return None
            raise
        return result.json()

    def _get_or_create_organizer(self, endpoint, name):
        """Categories/tags/tools all share this shape: POST {"name": ...},
        fall back to a name search if it already exists."""
        try:
            result = self._request("POST", endpoint, json={"name": name})
            return result.json()
        except HTTPError:
            existing = self._find_by_name(endpoint, name)
            if existing:
                return existing
            raise

    def create_or_update_recipe(self, recipe: Recipe):
        # Mealie always re-derives its own slug from the display name on
        # every write that touches "name" (including our main content PATCH
        # below), so a custom slug can't be pinned there - forcing a rename
        # gets silently undone or 500s on the next write in practice. We
        # don't fight that: recipe.slug (our local PK, the Cookidoo id) stays
        # our canonical identifier in our own DB; recipe.mealie_slug tracks
        # whatever slug Mealie currently has this recipe under, purely for
        # addressing API calls.
        recipe_existing = self.get_recipe(recipe.mealie_slug) if recipe.mealie_slug else None

        if not recipe_existing:
            mealie_slug = self.create_recipe(recipe)
            recipe_id = self.get_recipe(mealie_slug)["id"]
        else:
            mealie_slug = recipe_existing["slug"]
            recipe_id = recipe_existing["id"]

        if recipe.id != recipe_id:
            recipe.id = recipe_id
        recipe.mealie_slug = mealie_slug
        recipe.save()

        # Update recipe
        # settings excluded: we never populate it locally (always {}), and an
        # empty dict is a harmless no-op against Mealie anyway - excluding it
        # just keeps the payload honest about what we're actually sending.
        payload = recipe.to_api_data(exclude=["synced_hash", "last_synced_at", "mealie_slug", "slug", "settings"])
        payload["recipeInstructions"] = [
            {
                "title": instruction.title or "",
                "summary": instruction.summary or "",
                "text": instruction.formatted_text,
                "ingredientReferences": [],
            }
            for instruction in recipe.instruction_set.order_by("pk")
        ]
        payload["recipeCategory"] = [
            self._get_or_create_organizer("organizers/categories", c["name"]) for c in recipe.recipe_category
        ]
        payload["tags"] = [self._get_or_create_organizer("organizers/tags", t["name"]) for t in recipe.tags]
        payload["tools"] = [self._get_or_create_organizer("organizers/tools", t["name"]) for t in recipe.tools]
        result = self._request("PATCH", f"recipes/{mealie_slug}", json=payload)
        if result.status_code != 200:
            raise HTTPError(f"Unable to patch recipe {recipe.slug}, got {result.status_code}")

        # Update recipe image (non-fatal: the recipe content above already synced successfully)
        try:
            self._request("POST", f"recipes/{mealie_slug}/image", json={"url": recipe.image_url})
        except HTTPError as e:
            logger.warning("Failed to set image for recipe %s: %s", mealie_slug, e)

        return result.json()
