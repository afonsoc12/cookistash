import logging
import re
from urllib.parse import urlparse

from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError, Timeout

logger = logging.getLogger(__name__)


def friendly_error(action: str, exc: Exception) -> str:
    """Turn a scrape/sync exception into a short, UI-safe message.

    The full exception (which can include internal URLs like
    "http://mealie:9000/..." - meaningless, and slightly exposing, to a
    browser user) is always logged server-side with a traceback; only a
    generic summary is ever shown in the UI.
    """
    logger.exception("%s failed", action)
    if isinstance(exc, HTTPError) and exc.response is not None:
        return (
            f"{action} failed: the server responded with {exc.response.status_code}. "
            "Check Flower or the container logs for details."
        )
    if isinstance(exc, (RequestsConnectionError, Timeout)):
        return f"{action} failed: couldn't reach the server. Check it's running and reachable."
    return f"{action} failed: {exc}"


def parse_cookidoo_explore_url(url: str) -> tuple[str, str]:
    """Split a Cookidoo "explore" page URL into (base_url, locale).

    e.g. "https://cookidoo.pt/foundation/pt-PT/explore" ->
    ("https://cookidoo.pt/", "pt-PT") - the base URL is the domain (which
    differs per market: cookidoo.pt, cookidoo.thermomix.com, cookidoo.co.uk,
    ...), the locale is read straight from the URL path rather than assumed.
    """
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"'{url}' is not a valid URL")
    match = re.search(r"/([a-z]{2}-[A-Z]{2})(?:/|$)", parsed.path)
    if not match:
        raise ValueError(f"Couldn't find a locale (e.g. 'pt-PT') in the path of '{url}'")
    return f"{parsed.scheme}://{parsed.netloc}/", match.group(1)


def camel_to_snake(name):
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return re.sub(r"_+", "_", s)


def snake_to_camel(name):
    parts = name.split("_")
    return parts[0].casefold() + "".join(word.capitalize() for word in parts[1:])


def parse_recipe_id(text: str) -> str | None:
    """Extract a Cookidoo recipe ID (e.g. 'r123456') from a bare ID or a full recipe URL."""
    match = re.search(r"(r\d+)(?:[/?#]|$)", text.strip())
    return match.group(1) if match else None
