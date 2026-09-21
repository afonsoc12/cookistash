from django.db import migrations


TASK_NAME = "rescrape-stale-recipes-nightly"
TASK_PATH = "cookistash.cookidoo.tasks.rescrape_stale_recipes"


def seed_periodic_task(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    if PeriodicTask.objects.filter(name=TASK_NAME).exists():
        return

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="3", day_of_week="*", day_of_month="*", month_of_year="*",
    )
    PeriodicTask.objects.create(
        name=TASK_NAME,
        task=TASK_PATH,
        crontab=schedule,
        args="[7]",
        enabled=True,
        description="Re-scrapes (and re-syncs to Mealie, if content changed) "
                     "any recipe not scraped in the last N days.",
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cookidoo", "0003_scrapedrecipe_content_hash"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(seed_periodic_task, remove_periodic_task),
    ]
