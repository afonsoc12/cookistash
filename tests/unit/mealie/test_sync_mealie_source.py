import pytest
from django.core.management import call_command

from cookistash.mealie.models import Source

pytestmark = pytest.mark.django_db


class TestSyncMealieSource:
    def test_noop_when_api_url_unset(self, monkeypatch):
        monkeypatch.delenv("MEALIE_API_URL", raising=False)
        monkeypatch.setenv("MEALIE_API_TOKEN", "tok")
        call_command("sync_mealie_source")
        assert not Source.objects.exists()

    def test_noop_when_api_token_unset(self, monkeypatch):
        monkeypatch.setenv("MEALIE_API_URL", "http://mealie:9000")
        monkeypatch.delenv("MEALIE_API_TOKEN", raising=False)
        call_command("sync_mealie_source")
        assert not Source.objects.exists()

    def test_creates_source_when_none_exists(self, monkeypatch):
        monkeypatch.setenv("MEALIE_API_URL", "http://mealie:9000")
        monkeypatch.setenv("MEALIE_PUBLIC_URL", "http://localhost:9000")
        monkeypatch.setenv("MEALIE_GROUP_SLUG", "home")
        monkeypatch.setenv("MEALIE_API_TOKEN", "tok")
        call_command("sync_mealie_source")
        source = Source.objects.get()
        assert source.api_url == "http://mealie:9000"
        assert source.public_url == "http://localhost:9000"
        assert source.group_slug == "home"
        assert source.api_token == "tok"
        assert source.name == "Mealie"

    def test_defaults_group_slug_and_public_url_when_unset(self, monkeypatch):
        monkeypatch.setenv("MEALIE_API_URL", "http://mealie:9000")
        monkeypatch.delenv("MEALIE_PUBLIC_URL", raising=False)
        monkeypatch.delenv("MEALIE_GROUP_SLUG", raising=False)
        monkeypatch.setenv("MEALIE_API_TOKEN", "tok")
        call_command("sync_mealie_source")
        source = Source.objects.get()
        assert source.public_url == ""
        assert source.group_slug == "home"

    def test_updates_existing_source_when_env_var_changes(self, monkeypatch):
        Source.objects.create(name="Old", api_url="http://old:9000", api_token="old-tok")
        monkeypatch.setenv("MEALIE_API_URL", "http://mealie:9000")
        monkeypatch.setenv("MEALIE_API_TOKEN", "new-tok")
        call_command("sync_mealie_source")
        source = Source.objects.get()
        assert source.api_url == "http://mealie:9000"
        assert source.api_token == "new-tok"

    def test_leaves_up_to_date_source_untouched(self, monkeypatch):
        existing = Source.objects.create(
            name="Mealie", api_url="http://mealie:9000", public_url="", group_slug="home", api_token="tok"
        )
        monkeypatch.setenv("MEALIE_API_URL", "http://mealie:9000")
        monkeypatch.setenv("MEALIE_API_TOKEN", "tok")
        monkeypatch.delenv("MEALIE_PUBLIC_URL", raising=False)
        monkeypatch.setenv("MEALIE_GROUP_SLUG", "home")
        call_command("sync_mealie_source")
        existing.refresh_from_db()
        assert Source.objects.count() == 1
        assert existing.api_url == "http://mealie:9000"
