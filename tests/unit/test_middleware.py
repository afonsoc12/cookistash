import pytest
from django.contrib.auth.models import AnonymousUser, User

from cookistash.middleware import AutoAdminLoginMiddleware

pytestmark = pytest.mark.django_db


class TestAutoAdminLoginMiddleware:
    def _middleware(self, response="OK"):
        return AutoAdminLoginMiddleware(get_response=lambda request: response)

    def test_logs_in_as_first_superuser_when_enabled_and_anonymous(self, rf, settings):
        settings.AUTO_ADMIN_LOGIN = True
        User.objects.create_user(username="regular", password="x")
        superuser = User.objects.create_superuser(username="admin", password="x", email="a@example.com")

        request = rf.get("/")
        request.user = AnonymousUser()
        # AuthenticationMiddleware normally attaches a real session; the
        # auth backend's login() needs one to stash the user id in.
        from django.contrib.sessions.middleware import SessionMiddleware

        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()

        middleware = self._middleware()
        response = middleware(request)

        assert response == "OK"
        assert request.user == superuser

    def test_no_superuser_leaves_request_anonymous(self, rf, settings):
        settings.AUTO_ADMIN_LOGIN = True
        request = rf.get("/")
        request.user = AnonymousUser()

        middleware = self._middleware()
        response = middleware(request)

        assert response == "OK"
        assert request.user.is_authenticated is False

    def test_disabled_setting_skips_login(self, rf, settings):
        settings.AUTO_ADMIN_LOGIN = False
        User.objects.create_superuser(username="admin", password="x", email="a@example.com")
        request = rf.get("/")
        request.user = AnonymousUser()

        middleware = self._middleware()
        middleware(request)

        assert request.user.is_authenticated is False

    def test_already_authenticated_user_is_untouched(self, rf, settings):
        settings.AUTO_ADMIN_LOGIN = True
        existing = User.objects.create_user(username="regular", password="x")
        superuser = User.objects.create_superuser(username="admin", password="x", email="a@example.com")
        assert superuser  # a superuser exists but shouldn't be swapped in

        request = rf.get("/")
        request.user = existing

        middleware = self._middleware()
        middleware(request)

        assert request.user == existing
