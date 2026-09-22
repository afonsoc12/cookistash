from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

from cookistash.context_processors import app_version


class TestAppVersion:
    def test_returns_installed_version_and_release_url(self, rf):
        request = rf.get("/")
        with patch("cookistash.context_processors.version", return_value="1.2.3"):
            context = app_version(request)

        assert context["app_version"] == "1.2.3"
        assert context["app_release_url"] == "https://github.com/afonsoc12/cookistash/releases/tag/v1.2.3"

    def test_package_not_found_returns_none(self, rf):
        request = rf.get("/")
        with patch("cookistash.context_processors.version", side_effect=PackageNotFoundError):
            context = app_version(request)

        assert context["app_version"] is None
        assert context["app_release_url"] is None
