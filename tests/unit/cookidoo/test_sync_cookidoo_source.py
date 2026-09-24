import pytest
from django.core.management import call_command

from cookistash.cookidoo.models import Source

pytestmark = pytest.mark.django_db


class TestSyncCookidooSource:
    def test_noop_when_env_var_unset(self, monkeypatch):
        monkeypatch.delenv("COOKIDOO_EXPLORE_URL", raising=False)
        call_command("sync_cookidoo_source")
        assert not Source.objects.exists()

    def test_creates_source_when_none_exists(self, monkeypatch):
        monkeypatch.setenv("COOKIDOO_EXPLORE_URL", "https://cookidoo.pt/foundation/pt-PT/explore")
        call_command("sync_cookidoo_source")
        source = Source.objects.get()
        assert source.url == "https://cookidoo.pt/"
        assert source.locale == "pt-PT"
        assert source.name == "Cookidoo (pt-PT)"

    def test_updates_existing_source_when_env_var_changes(self, monkeypatch):
        Source.objects.create(name="Old", url="https://cookidoo.co.uk/", locale="en-GB")
        monkeypatch.setenv("COOKIDOO_EXPLORE_URL", "https://cookidoo.pt/foundation/pt-PT/explore")
        call_command("sync_cookidoo_source")
        source = Source.objects.get()
        assert source.url == "https://cookidoo.pt/"
        assert source.locale == "pt-PT"

    def test_leaves_up_to_date_source_untouched(self, monkeypatch):
        existing = Source.objects.create(name="Cookidoo (pt-PT)", url="https://cookidoo.pt/", locale="pt-PT")
        monkeypatch.setenv("COOKIDOO_EXPLORE_URL", "https://cookidoo.pt/foundation/pt-PT/explore")
        call_command("sync_cookidoo_source")
        existing.refresh_from_db()
        assert Source.objects.count() == 1
        assert existing.url == "https://cookidoo.pt/"
