import logging
from urllib.parse import urljoin

from requests import Session
from requests.exceptions import HTTPError

logger = logging.getLogger(__name__)


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
        category_ids = [
            "VrkNavigationCategory-rpf-000001303095",
            "VrkNavCategory-RPF-019",
            "VrkNavCategory-RPF-018",
            "VrkNavCategory-RPF-017",
            "VrkNavCategory-RPF-016",
            "VrkNavCategory-RPF-015",
            "VrkNavCategory-RPF-014",
            "VrkNavCategory-RPF-013",
            "VrkNavCategory-RPF-012",
            "VrkNavCategory-RPF-011",
            "VrkNavCategory-RPF-009",
            "VrkNavCategory-RPF-008",
            "VrkNavCategory-RPF-007",
            "VrkNavCategory-RPF-006",
            "VrkNavCategory-RPF-005",
            "VrkNavCategory-RPF-004",
            "VrkNavCategory-RPF-003",
            "VrkNavCategory-RPF-002",
            "VrkNavCategory-RPF-001",
            "VrkNavCategory-RPF-020",
        ]

        return category_ids
