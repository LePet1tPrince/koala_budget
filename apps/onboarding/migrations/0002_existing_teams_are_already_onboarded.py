"""
Teams that predate the walkthrough must not be thrown into it on deploy.

They already have a chart of accounts and, in most cases, real data. Marking them
complete is what keeps the `team_home` redirect from catching them.
"""

from django.db import migrations
from django.utils import timezone


def mark_existing_teams_onboarded(apps, schema_editor):
    Team = apps.get_model("teams", "Team")
    OnboardingState = apps.get_model("onboarding", "OnboardingState")

    now = timezone.now()
    OnboardingState.objects.bulk_create(
        [
            OnboardingState(
                team=team,
                answers={},
                tasks_done=[],
                phase="done",
                completed_at=now,
                created_at=now,
                updated_at=now,
            )
            for team in Team.objects.all()
        ],
        ignore_conflicts=True,
    )


def unmark(apps, schema_editor):
    apps.get_model("onboarding", "OnboardingState").objects.filter(answers={}, phase="done").delete()


class Migration(migrations.Migration):
    dependencies = [("onboarding", "0001_initial")]

    operations = [migrations.RunPython(mark_existing_teams_onboarded, unmark)]
