from unittest.mock import MagicMock

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError

from cookistash.utils import camel_to_snake, friendly_error, parse_cookidoo_explore_url, parse_recipe_id, snake_to_camel


@pytest.mark.parametrize(
    "input_str,expected",
    [
        ("unitRef", "unit_ref"),
        ("UnitRef", "unit_ref"),
        ("unitREF", "unit_r_e_f"),
        ("unit_Ref", "unit_ref"),
        ("unit__Ref", "unit_ref"),
        ("simple", "simple"),
        ("HTTPResponseCode", "h_t_t_p_response_code"),
        ("already_snake_case", "already_snake_case"),
    ],
)
def test_camel_to_snake(input_str, expected):
    assert camel_to_snake(input_str) == expected


@pytest.mark.parametrize(
    "input_str,expected",
    [
        ("unit_ref", "unitRef"),
        ("unit_r_e_f", "unitREF"),
        ("http_response_code", "httpResponseCode"),
        ("simple", "simple"),
        ("Snake_With_Caps", "snakeWithCaps"),
        ("already_snake_case", "alreadySnakeCase"),
    ],
)
def test_snake_to_camel(input_str, expected):
    assert snake_to_camel(input_str) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("r123456", "r123456"),
        ("https://cookidoo.co.uk/recipes/recipe/en-GB/r123456", "r123456"),
        ("https://cookidoo.co.uk/recipes/recipe/en-GB/r123456?foo=bar", "r123456"),
        ("https://cookidoo.co.uk/recipes/recipe/en-GB/r123456#section", "r123456"),
        ("some text ending in r99", "r99"),
        ("no id here", None),
        ("", None),
    ],
)
def test_parse_recipe_id(text, expected):
    assert parse_recipe_id(text) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://cookidoo.pt/foundation/pt-PT/explore", ("https://cookidoo.pt/", "pt-PT")),
        ("https://cookidoo.thermomix.com/foundation/en-US/explore", ("https://cookidoo.thermomix.com/", "en-US")),
        ("https://cookidoo.co.uk/foundation/en-GB/explore/", ("https://cookidoo.co.uk/", "en-GB")),
    ],
)
def test_parse_cookidoo_explore_url(url, expected):
    assert parse_cookidoo_explore_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "https://cookidoo.pt/foundation/explore",
        "",
    ],
)
def test_parse_cookidoo_explore_url_invalid(url):
    with pytest.raises(ValueError):
        parse_cookidoo_explore_url(url)


class TestFriendlyError:
    def test_http_error_hides_url_shows_status(self):
        response = MagicMock(status_code=500)
        exc = HTTPError("500 Server Error: Internal Server Error for url: http://mealie:9000/api/organizers/tags")
        exc.response = response

        message = friendly_error("Send to Mealie", exc)

        assert "500" in message
        assert "mealie:9000" not in message
        assert message.startswith("Send to Mealie failed:")

    def test_connection_error_is_generic(self):
        message = friendly_error("Send to Mealie", RequestsConnectionError("Failed to resolve 'mealie'"))
        assert message == "Send to Mealie failed: couldn't reach the server. Check it's running and reachable."

    def test_other_exceptions_fall_back_to_str(self):
        message = friendly_error("Scrape of r123", ValueError("something odd"))
        assert message == "Scrape of r123 failed: something odd"
