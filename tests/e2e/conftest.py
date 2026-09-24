"""Shared fixtures for the e2e suite.

These tests exercise the real scrape -> transform -> sync pipeline against
the live services from docker-compose (Postgres, Mealie) - only the actual
network call to Cookidoo is stubbed with fixture JSON (`data/recipes/`),
since hitting the real site in a test suite would be slow, rate-limit-prone,
and non-deterministic. Everything downstream (Django ORM, the Mealie HTTP
client, Mealie itself) is real.

Requires `docker compose up -d postgres redis mealie` beforehand - see
tests/e2e/README.md. Skipped in CI (see pyproject.toml `-m "not e2e"`).
"""

import json
from pathlib import Path

import pytest
import requests

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "recipes"
MEALIE_URL = "http://localhost:9000"


def _mealie_admin_token() -> str:
    """Log in as Mealie's default admin and mint a long-lived API token.

    Idempotent-ish: Mealie allows creating multiple tokens with the same
    name, so tests re-run cleanly without needing to track/delete old ones.
    """
    resp = requests.post(
        f"{MEALIE_URL}/api/auth/token",
        data={"username": "changeme@example.com", "password": "MyPassword"},
        timeout=10,
    )
    resp.raise_for_status()
    session_token = resp.json()["access_token"]

    resp = requests.post(
        f"{MEALIE_URL}/api/users/api-tokens",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"name": "cookistash-e2e-tests"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["token"]


@pytest.fixture
def cookidoo_source(db):
    from cookistash.cookidoo.models import Source

    return Source.objects.create(
        name="e2e Cookidoo",
        url="https://cookidoo.co.uk/",
        locale="en-GB",
    )


@pytest.fixture
def mealie_source(db):
    from cookistash.mealie.models import Source

    return Source.objects.create(
        name="e2e Mealie",
        api_url=MEALIE_URL,
        public_url=MEALIE_URL,
        group_slug="home",
        api_token=_mealie_admin_token(),
    )


@pytest.fixture
def stub_cookidoo_recipe(monkeypatch):
    """Make CookidooClient.get_recipe return fixture JSON instead of hitting
    the real Cookidoo site. Returns a callable so scenarios can pick which
    fixture recipe id to serve.
    """
    from cookistash.cookidoo import client as client_module

    def _install(recipe_id: str):
        data = json.loads((FIXTURE_DIR / f"{recipe_id}.json").read_text())

        def fake_get_recipe(self, requested_id):
            req = requests.Response()
            req.url = f"https://cookidoo.co.uk/recipes/recipe/en-GB/{requested_id}"
            return data, req

        def fake_test(self):
            return True

        monkeypatch.setattr(client_module.CookidooClient, "get_recipe", fake_get_recipe)
        monkeypatch.setattr(client_module.CookidooClient, "test", fake_test)
        return data

    return _install
