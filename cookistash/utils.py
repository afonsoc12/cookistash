import re


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
