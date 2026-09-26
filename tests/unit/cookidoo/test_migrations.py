import importlib

import pytest
from django.apps import apps
from django.contrib.auth.models import User

pytestmark = pytest.mark.django_db

migration_module = importlib.import_module("cookistash.cookidoo.migrations.0006_create_fallback_admin_user")
create_fallback_admin = migration_module.create_fallback_admin


class TestCreateFallbackAdminMigration:
    @pytest.fixture(autouse=True)
    def _not_test_doubles(self, settings):
        settings.USE_TEST_DOUBLES = False

    def test_creates_admin_admin_by_default_when_enabled_and_no_superuser(self, settings, monkeypatch):
        settings.AUTO_ADMIN_LOGIN = True
        monkeypatch.delenv("ADMIN_USERNAME", raising=False)
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

        create_fallback_admin(apps, None)

        user = User.objects.get(username="admin")
        assert user.is_superuser is True
        assert user.is_staff is True
        assert user.email == ""
        assert user.check_password("admin") is True

    def test_uses_env_vars_for_username_and_password(self, settings, monkeypatch):
        settings.AUTO_ADMIN_LOGIN = True
        monkeypatch.setenv("ADMIN_USERNAME", "root")
        monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")

        create_fallback_admin(apps, None)

        user = User.objects.get(username="root")
        assert user.check_password("s3cret") is True

    def test_skips_when_auto_admin_login_disabled(self, settings):
        settings.AUTO_ADMIN_LOGIN = False

        create_fallback_admin(apps, None)

        assert not User.objects.filter(username="admin").exists()

    def test_skips_when_a_superuser_already_exists(self, settings):
        settings.AUTO_ADMIN_LOGIN = True
        User.objects.create_superuser(username="existing", password="x", email="a@example.com")

        create_fallback_admin(apps, None)

        assert not User.objects.filter(username="admin").exists()
