"""`manage.py bootstrap_celery_tasks`: SCHEDULED_TASKS -> django-celery-beat rows."""

from io import StringIO

from celery import schedules
from django.core.management import call_command
from django.test import TestCase, override_settings
from django_celery_beat.models import PeriodicTask

TASKS = {
    "nightly": {"task": "apps.example.nightly", "schedule": schedules.crontab(minute=5, hour=3)},
    "broken": {"task": "apps.example.broken", "schedule": object()},
}


class BootstrapCeleryTasksTest(TestCase):
    def run_command(self, *args):
        out, err = StringIO(), StringIO()
        call_command("bootstrap_celery_tasks", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    @override_settings(SCHEDULED_TASKS=TASKS)
    def test_creates_tasks_and_skips_an_invalid_schedule(self):
        _out, err = self.run_command()
        task = PeriodicTask.objects.get(name="nightly")
        self.assertEqual(task.task, "apps.example.nightly")
        self.assertEqual((task.crontab.minute, task.crontab.hour), ("5", "3"))
        self.assertFalse(PeriodicTask.objects.filter(name="broken").exists())
        self.assertIn("Invalid schedule", err)

    @override_settings(SCHEDULED_TASKS=TASKS)
    def test_running_twice_does_not_lose_the_schedule(self):
        """It used to pop "schedule" out of the settings dict itself, so a second run crashed."""
        self.run_command()
        self.run_command()
        self.assertEqual(PeriodicTask.objects.filter(name="nightly").count(), 1)

    @override_settings(SCHEDULED_TASKS={"nightly": TASKS["nightly"]})
    def test_remove_stale(self):
        from django_celery_beat.models import IntervalSchedule

        every = IntervalSchedule.objects.create(every=1, period=IntervalSchedule.HOURS)
        PeriodicTask.objects.create(name="old", task="apps.example.old", interval=every)
        self.run_command("--remove-stale")
        self.assertFalse(PeriodicTask.objects.filter(name="old").exists())
