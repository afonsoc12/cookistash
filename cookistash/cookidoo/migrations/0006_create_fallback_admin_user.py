import os

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations


def create_fallback_admin(apps, schema_editor):
    if settings.USE_TEST_DOUBLES or not settings.AUTO_ADMIN_LOGIN:
        return

    User = apps.get_model("auth", "User")
    if User.objects.filter(is_superuser=True).exists():
        return

    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "admin")

    User.objects.create(
        username=username,
        email="",
        password=make_password(password),
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )


def remove_fallback_admin(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("cookidoo", "0005_remove_source_is_default_alter_source_url"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_fallback_admin, remove_fallback_admin),
    ]
