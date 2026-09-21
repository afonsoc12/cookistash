import logging
from urllib.parse import urljoin

from requests import Session
from requests.exceptions import HTTPError

logger = logging.getLogger(__name__)

# Cookidoo's recipe category taxonomy - ids are stable across locales, only
# the display title is localised server-side. Resolved once by hand (no
# public "list categories" endpoint exists), titles are the English default.
CATEGORIES = {
    "VrkNavigationCategory-rpf-000001303095": "Menus and more",
    "VrkNavCategory-RPF-019": "Breakfast",
    "VrkNavCategory-RPF-018": "Sauces, dips and spreads - savoury",
    "VrkNavCategory-RPF-017": "Baby food",
    "VrkNavCategory-RPF-016": "Basics",
    "VrkNavCategory-RPF-015": "Drinks",
    "VrkNavCategory-RPF-014": "Breads and rolls",
    "VrkNavCategory-RPF-013": "Baking - sweet",
    "VrkNavCategory-RPF-012": "Baking - savoury",
    "VrkNavCategory-RPF-011": "Desserts and sweets",
    "VrkNavCategory-RPF-009": "Sauces, dips and spreads - sweet",
    "VrkNavCategory-RPF-008": "Side dishes",
    "VrkNavCategory-RPF-007": "Main dishes - other",
    "VrkNavCategory-RPF-006": "Main dishes - vegetarian",
    "VrkNavCategory-RPF-005": "Main dishes - fish and seafood",
    "VrkNavCategory-RPF-004": "Main dishes - meat and poultry",
    "VrkNavCategory-RPF-003": "Pasta and rice dishes",
    "VrkNavCategory-RPF-002": "Soups",
    "VrkNavCategory-RPF-001": "Starters and salads",
    "VrkNavCategory-RPF-020": "Snacks and finger food",
}


class CookidooClient(Session):
    DEFAULT_HEADERS = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Cache-Control": "max-age=0",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",  # noqa: E501
    }

    def __init__(self, source):
        super().__init__()
        self.url = source.url
        self.locale = source.locale
        self.headers.update(source.headers if source.headers else self.DEFAULT_HEADERS)
        self.test()

    def __repr__(self):
        return f"{self.__class__.__name__}('{self.url}')"

    def request(self, method, endpoint, *args, **kwargs):  # type: ignore[override]
        if endpoint.startswith("/") or endpoint.endswith("/"):
            raise ValueError("Endpoint must not start or end with '/'")
        req = super().request(method, urljoin(self.url, endpoint), *args, **kwargs)
        try:
            req.raise_for_status()
        except HTTPError as e:
            raise HTTPError(f"Status code is {req.status_code} for request {endpoint}: {e}") from e

        return req

    def test(self):
        """Raises if status_code is not 2xx."""
        _ = self.request("GET", "search/abcd")
        return True

    def get_recipe(self, recipe_id):
        req = self.request("GET", f"recipes/recipe/{self.locale}/{recipe_id}")
        return req.json(), req

    def search(self, category=None, page=0, limit=24, sortby=None, rating=None):
        """Search recipes for the Discover UI - a thin, paginated wrapper
        around the same search endpoint get_country_recipes() uses in bulk.
        Returns the raw list of result dicts (id, title, image, rating, totalTime, ...).
        """
        params = {"page": page, "limit": limit}
        if category:
            params["categories"] = category
        if sortby:
            params["sortby"] = sortby
        if rating:
            params["rating"] = rating
        result = self.request("GET", f"search/{self.locale}", params=params)
        return result.json()["data"]

    def get_country_recipes(self, country):
        """Retrieves all Recipe IDs for a country

        A limitation of the API is that it can only retrieve a maximum of 1000 requests.
        To bypass this, use multiple filter rules to fetch all recipes available
        """
        recipe_ids = set()

        # Use sort by filters
        for sort_by in (
            "relevance",
            "publishedat",
            "title",
            "totalTime",
            "preparationTime",
            "rating",
        ):
            for order in ("", "-"):
                result = self.request(
                    "GET",
                    f"search/{self.locale}",
                    params={
                        "countries": country,
                        "page": 0,
                        "limit": 1000,
                        "sortby": f"{order}{sort_by}",
                    },
                )
                processed_recipe_ids = self._process_recipe_ids(result.json())
                logger.debug(f"Found {len(processed_recipe_ids)} for filter '{order}{sort_by}'")
                recipe_ids.update(processed_recipe_ids)

        # Use multiple ratings
        for rating in range(1, 6):
            result = self.request(
                "GET",
                f"search/{self.locale}",
                params={
                    "countries": country,
                    "page": 0,
                    "limit": 1000,
                    "rating": rating,
                },
            )
            processed_recipe_ids = self._process_recipe_ids(result.json())
            logger.debug(f"Found {len(processed_recipe_ids)} for rating {rating}")
            recipe_ids.update(processed_recipe_ids)

        # Use categories
        for cat in self._get_all_categories():
            result = self.request(
                "GET",
                f"search/{self.locale}",
                params={
                    "countries": country,
                    "page": 0,
                    "limit": 1000,
                    "categories": cat,
                },
            )
            processed_recipe_ids = self._process_recipe_ids(result.json())
            logger.debug(f"Found {len(processed_recipe_ids)} for category '{cat}'")
            recipe_ids.update(processed_recipe_ids)

        logger.debug(f"Found {len(recipe_ids)} unique recipes for country {country}")
        return recipe_ids

    def _process_recipe_ids(self, data):
        return {r["id"] for r in data["data"]}

    def _get_all_categories(self):
        return list(CATEGORIES.keys())
