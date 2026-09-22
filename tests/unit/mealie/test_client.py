from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from requests import HTTPError, Session

from cookistash.mealie.client import MealieClient
from cookistash.mealie.models import Food, Instruction, Recipe, Source, Unit

pytestmark = pytest.mark.django_db


@pytest.fixture
def mock_session():
    with patch.object(Session, "request", return_value=MagicMock(status_code=200)) as mock_session:
        yield mock_session


@pytest.fixture
def source():
    return Source.objects.create(name="Mealie", api_url="https://mealie.example.com", api_token="secrettoken")


@pytest.fixture
def mealie_client(source):
    with patch.object(MealieClient, "test", return_value=True):
        yield MealieClient(source)


def _duplicate_key_error(existing_item):
    response = MagicMock()
    response.json.return_value = {"detail": {"exception": "duplicate key value violates unique constraint"}}
    error = HTTPError(response=response)
    return error


class TestInit:
    def test_sets_url_and_auth_header(self, mealie_client, source):
        assert mealie_client.url == source.api_url
        assert mealie_client.headers["Authorization"] == f"Bearer {source.api_token}"

    def test_repr(self, mealie_client):
        assert mealie_client.__repr__() == "MealieClient('https://mealie.example.com/api/')"


class TestRequest:
    @pytest.mark.parametrize("endpoint", ["/foods", "foods/", "/foods/"])
    def test_rejects_leading_trailing_slash(self, mealie_client, endpoint):
        with pytest.raises(ValueError, match="Endpoint must not start or end with '/'"):
            mealie_client._request("GET", endpoint)

    def test_test_calls_app_about_endpoint(self, source, mock_session):
        # Unlike `mealie_client`, don't pre-patch .test() here - we're
        # testing its real implementation, not bypassing it.
        MealieClient(source)
        mock_session.assert_called_once_with("GET", "https://mealie.example.com/api/app/about")

    def test_test_raises_on_http_error(self, source, mock_session):
        mock_session.return_value.raise_for_status.side_effect = HTTPError()
        with pytest.raises(HTTPError):
            MealieClient(source)


class TestParseResponse:
    @pytest.mark.parametrize("status", [200, 201])
    def test_success_statuses_return_json(self, mealie_client, status):
        response = MagicMock(status_code=status)
        response.json.return_value = {"ok": True}
        data, code = mealie_client.parse_response(response)
        assert data == {"ok": True}
        assert code == status

    def test_other_statuses_return_none(self, mealie_client):
        response = MagicMock(status_code=404)
        data, code = mealie_client.parse_response(response)
        assert data is None
        assert code == 404


class TestFindByName:
    def test_returns_matching_item(self, mealie_client):
        with patch.object(mealie_client, "_request") as mock_request:
            mock_request.return_value.json.return_value = {"items": [{"name": "Other"}, {"name": "Salt"}]}
            result = mealie_client._find_by_name("foods", "Salt")
        assert result == {"name": "Salt"}

    def test_returns_none_when_not_found(self, mealie_client):
        with patch.object(mealie_client, "_request") as mock_request:
            mock_request.return_value.json.return_value = {"items": []}
            result = mealie_client._find_by_name("foods", "Salt")
        assert result is None

    def test_match_is_case_insensitive(self, mealie_client):
        # Mealie's own uniqueness constraint on these names is case-insensitive
        # (POSTing "vegetarian" when "Vegetarian" exists 500s rather than
        # 409ing) - the fallback lookup has to match the same way or it'll
        # never find the row that caused the conflict in the first place.
        with patch.object(mealie_client, "_request") as mock_request:
            mock_request.return_value.json.return_value = {"items": [{"name": "Vegetarian"}]}
            result = mealie_client._find_by_name("organizers/tags", "vegetarian")
        assert result == {"name": "Vegetarian"}


class TestCreateFood:
    def test_creates_and_stores_mealie_id(self, mealie_client):
        food = Food.objects.create(name="Salt")
        new_id = str(uuid4())
        with patch.object(mealie_client, "_request") as mock_request:
            mock_request.return_value.json.return_value = {"id": new_id, "name": "Salt"}
            result = mealie_client.create_food(food)

        food.refresh_from_db()
        assert result["id"] == new_id
        assert str(food.mealie_id) == new_id

    def test_duplicate_key_falls_back_to_name_search(self, mealie_client):
        food = Food.objects.create(name="Salt")
        existing_id = str(uuid4())
        with patch.object(mealie_client, "_request") as mock_request:
            mock_request.side_effect = [
                _duplicate_key_error(None),
                MagicMock(json=lambda: {"items": [{"id": existing_id, "name": "Salt"}]}),
            ]
            result = mealie_client.create_food(food)

        food.refresh_from_db()
        assert result["id"] == existing_id
        assert str(food.mealie_id) == existing_id

    def test_non_duplicate_http_error_reraises(self, mealie_client):
        food = Food.objects.create(name="Salt")
        response = MagicMock()
        response.json.return_value = {"detail": {"exception": "something else broke"}}
        with patch.object(mealie_client, "_request", side_effect=HTTPError(response=response)):
            with pytest.raises(HTTPError):
                mealie_client.create_food(food)

    def test_matching_mealie_id_does_not_resave(self, mealie_client):
        existing_id = uuid4()
        food = Food.objects.create(name="Salt", mealie_id=existing_id)
        with patch.object(mealie_client, "_request") as mock_request:
            mock_request.return_value.json.return_value = {"id": str(existing_id), "name": "Salt"}
            with patch.object(food, "save") as mock_save:
                mealie_client.create_food(food)
                mock_save.assert_not_called()


class TestCreateUnit:
    def test_creates_and_stores_mealie_id(self, mealie_client):
        unit = Unit.objects.create(name="g")
        new_id = str(uuid4())
        with patch.object(mealie_client, "_request") as mock_request:
            mock_request.return_value.json.return_value = {"id": new_id, "name": "g"}
            result = mealie_client.create_unit(unit)

        unit.refresh_from_db()
        assert result["id"] == new_id
        assert str(unit.mealie_id) == new_id

    def test_duplicate_key_falls_back_to_name_search(self, mealie_client):
        unit = Unit.objects.create(name="g")
        existing_id = str(uuid4())
        with patch.object(mealie_client, "_request") as mock_request:
            mock_request.side_effect = [
                _duplicate_key_error(None),
                MagicMock(json=lambda: {"items": [{"id": existing_id, "name": "g"}]}),
            ]
            result = mealie_client.create_unit(unit)

        unit.refresh_from_db()
        assert result["id"] == existing_id
        assert str(unit.mealie_id) == existing_id


class TestCreateRecipe:
    def test_posts_name_only(self, mealie_client):
        with patch.object(mealie_client, "_request") as mock_request:
            mock_request.return_value.json.return_value = "some-slug"
            result = mealie_client.create_recipe(MagicMock(name="Gazpacho"))
        assert result == "some-slug"


class TestGetRecipe:
    def test_returns_json_on_success(self, mealie_client):
        with patch.object(mealie_client, "_request") as mock_request:
            mock_request.return_value.json.return_value = {"slug": "gazpacho"}
            result = mealie_client.get_recipe("gazpacho")
        assert result == {"slug": "gazpacho"}

    def test_returns_none_on_404_no_entry_found(self, mealie_client):
        response = MagicMock(status_code=404)
        response.json.return_value = {"detail": {"message": "No Entry Found"}}
        with patch.object(mealie_client, "_request", side_effect=HTTPError(response=response)):
            result = mealie_client.get_recipe("missing")
        assert result is None

    def test_reraises_other_404_messages(self, mealie_client):
        response = MagicMock(status_code=404)
        response.json.return_value = {"detail": {"message": "Something else"}}
        with patch.object(mealie_client, "_request", side_effect=HTTPError(response=response)):
            with pytest.raises(HTTPError):
                mealie_client.get_recipe("missing")

    def test_reraises_non_404_errors(self, mealie_client):
        response = MagicMock(status_code=500)
        with patch.object(mealie_client, "_request", side_effect=HTTPError(response=response)):
            with pytest.raises(HTTPError):
                mealie_client.get_recipe("broken")


class TestGetOrCreateOrganizer:
    def test_creates_when_post_succeeds(self, mealie_client):
        with patch.object(mealie_client, "_request") as mock_request:
            mock_request.return_value.json.return_value = {"name": "Dessert"}
            result = mealie_client._get_or_create_organizer("organizers/categories", "Dessert")
        assert result == {"name": "Dessert"}

    def test_falls_back_to_search_on_error(self, mealie_client):
        with (
            patch.object(mealie_client, "_request", side_effect=HTTPError()),
            patch.object(mealie_client, "_find_by_name", return_value={"name": "Dessert"}),
        ):
            result = mealie_client._get_or_create_organizer("organizers/categories", "Dessert")
        assert result == {"name": "Dessert"}

    def test_reraises_when_not_found_either_way(self, mealie_client):
        with (
            patch.object(mealie_client, "_request", side_effect=HTTPError()),
            patch.object(mealie_client, "_find_by_name", return_value=None),
        ):
            with pytest.raises(HTTPError):
                mealie_client._get_or_create_organizer("organizers/categories", "Dessert")


@pytest.fixture
def mealie_recipe():
    from datetime import datetime

    from cookistash.cookidoo.models import Recipe as CookidooRecipe
    from cookistash.cookidoo.models import ScrapedRecipe

    cookidoo_source = None
    cookidoo_recipe = CookidooRecipe.objects.create(
        id="r123", name="Gazpacho", language="en", markets=[], status="ok", publication_date=datetime.now()
    )
    scraped = ScrapedRecipe.objects.create(recipe=cookidoo_recipe, source=cookidoo_source, success=True)
    recipe = Recipe.objects.create(
        recipe=cookidoo_recipe,
        scraped_recipe=scraped,
        name="Gazpacho",
        image_url="https://example.com/img.jpg",
        org_url="https://cookidoo.example.com/r123",
    )
    Instruction.objects.create(recipe=recipe, title=None, summary="Step 1", formatted_text="Chop everything")
    return recipe


class TestCreateOrUpdateRecipe:
    def test_creates_new_recipe_when_no_mealie_slug(self, mealie_client, mealie_recipe):
        # recipe.mealie_slug is unset, so the "does it already exist" lookup
        # is skipped entirely and get_recipe is only called once, after create.
        new_id = str(uuid4())
        with (
            patch.object(mealie_client, "get_recipe", return_value={"id": new_id}),
            patch.object(mealie_client, "create_recipe", return_value="gazpacho-slug"),
            patch.object(mealie_client, "_get_or_create_organizer", return_value={"name": "x"}),
            patch.object(mealie_client, "_request") as mock_request,
        ):
            mock_request.return_value.status_code = 200
            mock_request.return_value.json.return_value = {"slug": "gazpacho-slug"}
            result = mealie_client.create_or_update_recipe(mealie_recipe)

        mealie_recipe.refresh_from_db()
        assert mealie_recipe.mealie_slug == "gazpacho-slug"
        assert str(mealie_recipe.id) == new_id
        assert result == {"slug": "gazpacho-slug"}

    def test_updates_existing_recipe_by_current_mealie_slug(self, mealie_client, mealie_recipe):
        mealie_recipe.mealie_slug = "old-slug"
        mealie_recipe.save()
        existing_id = str(uuid4())

        with (
            patch.object(mealie_client, "get_recipe", return_value={"slug": "renamed-slug", "id": existing_id}),
            patch.object(mealie_client, "_get_or_create_organizer", return_value={"name": "x"}),
            patch.object(mealie_client, "_request") as mock_request,
        ):
            mock_request.return_value.status_code = 200
            mock_request.return_value.json.return_value = {"slug": "renamed-slug"}
            mealie_client.create_or_update_recipe(mealie_recipe)

        mealie_recipe.refresh_from_db()
        assert mealie_recipe.mealie_slug == "renamed-slug"

    def test_raises_when_patch_status_not_200(self, mealie_client, mealie_recipe):
        with (
            patch.object(mealie_client, "get_recipe", return_value={"id": str(uuid4())}),
            patch.object(mealie_client, "create_recipe", return_value="gazpacho-slug"),
            patch.object(mealie_client, "_get_or_create_organizer", return_value={"name": "x"}),
            patch.object(mealie_client, "_request") as mock_request,
        ):
            mock_request.return_value.status_code = 500
            with pytest.raises(HTTPError):
                mealie_client.create_or_update_recipe(mealie_recipe)

    def test_image_update_failure_is_non_fatal(self, mealie_client, mealie_recipe):
        def side_effects(method, endpoint, *args, **kwargs):
            if method == "PATCH":
                resp = MagicMock(status_code=200)
                resp.json.return_value = {"slug": "gazpacho-slug"}
                return resp
            if endpoint.endswith("/image"):
                raise HTTPError("image upload failed")
            raise AssertionError(f"unexpected call {method} {endpoint}")

        with (
            patch.object(mealie_client, "get_recipe", return_value={"id": str(uuid4())}),
            patch.object(mealie_client, "create_recipe", return_value="gazpacho-slug"),
            patch.object(mealie_client, "_get_or_create_organizer", return_value={"name": "x"}),
            patch.object(mealie_client, "_request", side_effect=side_effects),
        ):
            result = mealie_client.create_or_update_recipe(mealie_recipe)

        assert result == {"slug": "gazpacho-slug"}
