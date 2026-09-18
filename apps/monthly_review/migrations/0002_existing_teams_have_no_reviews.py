"""
Deliberately a no-op.

Unlike onboarding, there is nothing to backfill: a team with no
`MonthlyReviewState` row simply has no reviewed months yet, which is exactly
the state a brand new team should be in. This migration exists only to record
that decision -- do not add a RunPython here that manufactures state rows for
existing teams.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("monthly_review", "0001_initial")]

    operations = []
