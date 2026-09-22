from datetime import datetime
from unittest.mock import patch

import pytest
from django.urls import reverse

from cookistash.cookidoo.models import Recipe, Source

pytestmark = pytest.mark.django_db


class TestDiscover:
    def test_no_source_configured(self, client):
        resp = client.get(reverse("cookidoo:discover"))
        assert resp.status_code == 200
        assert resp.context["has_cookidoo_source"] is False
        assert resp.context["results"] == []

    def test_lists_results_and_flags_already_scraped(self, client):
        Source.objects.create(name="S", url="https://example.com", locale="en-GB", is_default=True)
        Recipe.objects.create(
            id="r1", name="Known", language="en", markets=[], status="ok", publication_date=datetime.now()
        )
        mock_results = [
            {"id": "r1", "title": "Known"},
            {"id": "r2", "title": "New"},
        ]
        with (
            patch("cookistash.cookidoo.views.CookidooClient.test", return_value=True),
            patch("cookistash.cookidoo.views.CookidooClient.search", return_value=mock_results),
        ):
            resp = client.get(reverse("cookidoo:discover"), {"category": "cat1"})

        assert resp.status_code == 200
        by_id = {r["id"]: r for r in resp.context["results"]}
        assert by_id["r1"]["already_scraped"] is True
        assert by_id["r2"]["already_scraped"] is False

    def test_fetch_error_is_surfaced_not_raised(self, client):
        Source.objects.create(name="S", url="https://example.com", locale="en-GB", is_default=True)
        with patch("cookistash.cookidoo.views.CookidooClient.__init__", side_effect=Exception("boom")):
            resp = client.get(reverse("cookidoo:discover"))

        assert resp.status_code == 200
        assert "boom" in resp.context["fetch_error"]


class TestDiscoverImport:
    def test_import_success_redirects_to_discover(self, client):
        with patch("cookistash.cookidoo.views.scrape_recipe.apply") as mock_apply:
            mock_apply.return_value.get.return_value = "some-task-id"
            resp = client.post(
                reverse("cookidoo:discover_import", args=["r99"]),
                {"category": "cat1", "page": "2"},
            )

        assert resp.status_code == 200
        mock_apply.assert_called_once_with(args=("r99",))

    def test_import_failure_shows_message(self, client):
        with patch("cookistash.cookidoo.views.scrape_recipe.apply", side_effect=Exception("scrape failed")):
            resp = client.post(reverse("cookidoo:discover_import", args=["r99"]), {})

        assert resp.status_code == 200
        messages = list(resp.context["messages"])
        assert any("scrape failed" in str(m) for m in messages)
