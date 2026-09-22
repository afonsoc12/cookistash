from unittest.mock import MagicMock, patch

import pytest
from requests import HTTPError, Session

from cookistash.cookidoo.client import CookidooClient
from cookistash.cookidoo.models import Source


@pytest.mark.django_db
class TestCookidooClient:
    @pytest.fixture
    def mock_session(self):
        with patch.object(Session, "request", return_value=MagicMock(status_code=200)) as mock_session:
            yield mock_session

    @pytest.fixture
    def source(self, request):
        headers = getattr(request, "param", None)
        yield Source.objects.create(
            name="test source", url="https://example.com", locale="en-GB", headers=headers or {}
        )

    @pytest.fixture
    def cookidoo_client(self, source):
        with patch.object(CookidooClient, "test", return_value=True):
            yield CookidooClient(source)

    def test_init_default_headers(self, cookidoo_client, source):
        assert cookidoo_client.url == source.url
        assert cookidoo_client.locale == source.locale
        assert all(item in cookidoo_client.headers.items() for item in CookidooClient.DEFAULT_HEADERS.items())

    @pytest.mark.parametrize("source", [pytest.param({"Custom Header": "Test 123"})], indirect=True)
    def test_init_custom_headers(self, cookidoo_client, source):
        assert cookidoo_client.url == source.url
        assert cookidoo_client.locale == source.locale
        assert all(item in cookidoo_client.headers.items() for item in source.headers.items())

    def test_repr(self, cookidoo_client):
        assert cookidoo_client.__repr__() == f"CookidooClient('{cookidoo_client.url}')"

    @pytest.mark.parametrize("endpoint", ["test-endpoint", "test-endpoint/a", "test-endpoint/a/b"])
    def test_request(self, cookidoo_client, endpoint, mock_session):

        method = "GET"
        endpoint = "test-endpoint"
        _ = cookidoo_client.request(method, endpoint)
        mock_session.assert_called_once_with(method, f"{cookidoo_client.url}/{endpoint}")

    @pytest.mark.parametrize("endpoint", ["/test-endpoint", "test-endpoint/", "/test-endpoint/"])
    def test_request_cannot_start_end_slash(self, cookidoo_client, endpoint):
        with pytest.raises(ValueError, match="Endpoint must not start or end with '/'"):
            _ = cookidoo_client.request("GET", endpoint)

    def test_test_successful(self, cookidoo_client, mock_session):
        assert cookidoo_client.test() is True

    # def test_test_raises_http_error(self, source, ):
    #     # mock_session.return_value.status_code = 606

    #     client = CookidooClient(source=source).test()

    def test_test_failure(self, source, mock_session):
        """test() should raise HTTPError when request fails (status != 200)"""
        mock_session.return_value.status_code = 606
        mock_session.return_value.raise_for_status.side_effect = HTTPError()

        with pytest.raises(HTTPError, match="Status code is 606"):
            _ = CookidooClient(source)

        mock_session.assert_called_once_with("GET", f"{source.url}/search/abcd")

    def test_get_recipe(self, cookidoo_client, mock_session):
        cookidoo_client.get_recipe("r1234")
        mock_session.assert_called_once_with(
            "GET", f"{cookidoo_client.url}/recipes/recipe/{cookidoo_client.locale}/r1234"
        )

    def test_search(self, cookidoo_client):
        mock_data = {"data": [{"id": "r1", "title": "Soup"}, {"id": "r2", "title": "Cake"}]}
        with patch.object(cookidoo_client, "request", return_value=MagicMock(json=lambda: mock_data)) as mock_request:
            results = cookidoo_client.search(category="cat1", page=1, limit=10, sortby="rating", rating=5)

        assert results == mock_data["data"]
        mock_request.assert_called_once_with(
            "GET",
            f"search/{cookidoo_client.locale}",
            params={"page": 1, "limit": 10, "categories": "cat1", "sortby": "rating", "rating": 5},
        )

    def test_search_no_category(self, cookidoo_client):
        mock_data = {"data": []}
        with patch.object(cookidoo_client, "request", return_value=MagicMock(json=lambda: mock_data)) as mock_request:
            cookidoo_client.search()

        mock_request.assert_called_once_with("GET", f"search/{cookidoo_client.locale}", params={"page": 0, "limit": 24})

    @pytest.mark.parametrize("country", ["pt", "uk"])
    def test_get_country_recipes(self, cookidoo_client, country):

        # Mock the _process_recipe_ids method to just return the ids from input
        cookidoo_client._process_recipe_ids = lambda data: {r["id"] for r in data["data"]}
        cookidoo_client._get_all_categories = lambda: ["cat1", "cat2"]

        # Mock response data
        mock_data = {"data": [{"id": "r1"}, {"id": "r2"}]}

        with patch.object(cookidoo_client, "request", return_value=MagicMock(json=lambda: mock_data)) as mock_request:
            recipe_ids = cookidoo_client.get_country_recipes(country)

        # All recipe IDs from all calls should be in the set
        assert recipe_ids == {"r1", "r2"}

        # request should be called multiple times (sorts + ratings + categories)
        # 6 sort_by * 2 orders = 12, 5 ratings, 2 categories -> 19 calls
        assert mock_request.call_count == 12 + 5 + 2
