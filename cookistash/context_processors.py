from importlib.metadata import PackageNotFoundError, version


def app_version(request):
    try:
        app_version_str = version("cookistash")
    except PackageNotFoundError:
        app_version_str = None
    return {
        "app_version": app_version_str,
        "app_release_url": (
            f"https://github.com/afonsoc12/cookistash/releases/tag/v{app_version_str}" if app_version_str else None
        ),
    }
