import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cookistash.settings")

app = Celery(__package__)

# Load config from Django settings, prefixing celery-related keys with CELERY_
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py inside your Django apps
app.autodiscover_tasks()
