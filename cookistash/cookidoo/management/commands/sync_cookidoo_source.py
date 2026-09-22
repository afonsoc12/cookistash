import os

from django.core.management.base import BaseCommand

from cookistash.cookidoo.models import Source
from cookistash.utils import parse_cookidoo_explore_url


class Command(BaseCommand):
    help = (
        "Create/update the single Cookidoo Source from the COOKIDOO_EXPLORE_URL env var "
        "(e.g. https://cookidoo.pt/foundation/pt-PT/explore). No-op if the env var isn't set - "
        "there's no hardcoded default, an existing source is left untouched, and a missing one "
        "just means Cookidoo isn't configured yet."
    )

    def handle(self, *args, **options):
        explore_url = os.environ.get("COOKIDOO_EXPLORE_URL")
        if not explore_url:
            self.stdout.write("COOKIDOO_EXPLORE_URL not set, skipping Cookidoo source sync.")
            return

        url, locale = parse_cookidoo_explore_url(explore_url)
        name = f"Cookidoo ({locale})"

        source = Source.objects.first()
        if source is None:
            Source.objects.create(name=name, url=url, locale=locale)
            self.stdout.write(self.style.SUCCESS(f"Created Cookidoo source: {name} ({url})"))
        elif (source.url, source.locale) != (url, locale):
            source.name, source.url, source.locale = name, url, locale
            source.save()
            self.stdout.write(self.style.SUCCESS(f"Updated Cookidoo source: {name} ({url})"))
        else:
            self.stdout.write("Cookidoo source already up to date.")
