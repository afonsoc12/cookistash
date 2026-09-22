import os

from django.core.management.base import BaseCommand

from cookistash.mealie.models import Source


class Command(BaseCommand):
    help = (
        "Create/update the single Mealie Source from MEALIE_API_URL/MEALIE_API_TOKEN "
        "(+ optional MEALIE_PUBLIC_URL/MEALIE_GROUP_SLUG) env vars. No-op if MEALIE_API_URL or "
        "MEALIE_API_TOKEN isn't set - there's no hardcoded default, an existing source is left "
        "untouched, and a missing one just means Mealie sync isn't configured yet."
    )

    def handle(self, *args, **options):
        api_url = os.environ.get("MEALIE_API_URL")
        api_token = os.environ.get("MEALIE_API_TOKEN")
        if not api_url or not api_token:
            self.stdout.write("MEALIE_API_URL/MEALIE_API_TOKEN not set, skipping Mealie source sync.")
            return

        public_url = os.environ.get("MEALIE_PUBLIC_URL", "")
        group_slug = os.environ.get("MEALIE_GROUP_SLUG", "home")
        name = "Mealie"

        desired = {
            "name": name,
            "api_url": api_url,
            "public_url": public_url,
            "group_slug": group_slug,
            "api_token": api_token,
        }

        source = Source.objects.first()
        if source is None:
            Source.objects.create(**desired)
            self.stdout.write(self.style.SUCCESS(f"Created Mealie source: {name} ({api_url})"))
            return

        current = {
            "name": source.name,
            "api_url": source.api_url,
            "public_url": source.public_url or "",
            "group_slug": source.group_slug,
            "api_token": source.api_token,
        }
        if current != desired:
            for field, value in desired.items():
                setattr(source, field, value)
            source.save()
            self.stdout.write(self.style.SUCCESS(f"Updated Mealie source: {name} ({api_url})"))
        else:
            self.stdout.write("Mealie source already up to date.")
