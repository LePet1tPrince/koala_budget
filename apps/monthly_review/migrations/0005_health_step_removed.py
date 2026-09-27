from django.db import migrations

# The data-completeness check was walkthrough step 0; it is now a modal that
# opens the review. Every stored step index after it moves down by one.


def shift_down(apps, schema_editor):
    MonthlyReviewState = apps.get_model("monthly_review", "MonthlyReviewState")
    for state in MonthlyReviewState.objects.all().only("id", "step", "steps_seen"):
        state.step = max(state.step - 1, 0)
        state.steps_seen = sorted({s - 1 for s in state.steps_seen or [] if isinstance(s, int) and s > 0})
        state.save(update_fields=["step", "steps_seen"])


def shift_up(apps, schema_editor):
    MonthlyReviewState = apps.get_model("monthly_review", "MonthlyReviewState")
    for state in MonthlyReviewState.objects.all().only("id", "step", "steps_seen"):
        state.step = state.step + 1
        state.steps_seen = sorted({s + 1 for s in state.steps_seen or [] if isinstance(s, int)})
        state.save(update_fields=["step", "steps_seen"])


class Migration(migrations.Migration):
    dependencies = [
        ("monthly_review", "0004_book_required"),
    ]

    operations = [
        migrations.RunPython(shift_down, shift_up),
    ]
