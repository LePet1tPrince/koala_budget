"""Response shape of the book dashboard endpoint (`GET /a/{team}/{book}/api/home/`)."""

from rest_framework import serializers

from apps.api.base import MonthField

from .services.home import YNAB_FAILED, YNAB_RUNNING


def _money(**kwargs):
    return serializers.DecimalField(max_digits=15, decimal_places=2, **kwargs)


class HomeIncomeSerializer(serializers.Serializer):
    start_date = serializers.DateField(help_text="January 1st of this year.")
    end_date = serializers.DateField(help_text="Today.")
    income = _money()
    expenses = _money()
    net = _money(help_text="Income − expenses, year to date.")


class HomeGoalSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    has_target = serializers.BooleanField(help_text="False for an open-ended goal (a monthly contribution alone).")
    target_amount = _money()
    allocated = _money(help_text="Set aside so far, as of the end of this month.")
    spent = _money(help_text="Spent from the goal so far.")
    left = _money(help_text="Allocated − spent.")
    progress_percentage = serializers.FloatField(help_text="Allocated / target, 0–100; 0 for an open-ended goal.")


class HomeTrendPointSerializer(serializers.Serializer):
    date = serializers.DateField(help_text="A month end (the last point is today).")
    net_worth = _money()


class HomeYnabImportSerializer(serializers.Serializer):
    offered = serializers.BooleanField(help_text="The YNAB import is on and the book has no transactions yet.")
    state = serializers.ChoiceField(
        choices=["", YNAB_RUNNING, YNAB_FAILED],
        allow_blank=True,
        help_text="An import still going or one that failed; blank for neither.",
    )


class HomeMonthlyReviewNudgeSerializer(serializers.Serializer):
    month = MonthField(help_text="Last month: it has activity and was neither reviewed nor dismissed.")


class BookHomeSerializer(serializers.Serializer):
    """The book's dashboard: headline figures, the first goals, the net-worth trend and its nudges."""

    month = MonthField(help_text="The current month.")
    greeting = serializers.CharField(help_text="A greeting for the user, rotating daily.")
    book_label = serializers.CharField(allow_blank=True, help_text="The book's name once the team has several.")
    onboarding_finished = serializers.BooleanField(
        help_text="False while the guided walkthrough is unfinished: the web app sends the user there."
    )
    net_worth = _money(help_text="Assets − liabilities at the end of this month.")
    income_ytd = HomeIncomeSerializer()
    amount_to_reach_goals = _money(help_text="What open goals still ask for: Σ (target − allocated), never negative.")
    goals = HomeGoalSerializer(many=True, help_text="The first few open goals (the Goals page lists them all).")
    net_worth_trend = HomeTrendPointSerializer(
        many=True, help_text="Month-end net worth from the book's first activity to today."
    )
    show_resume = serializers.BooleanField(
        help_text="Offer to pick the guided setup back up (skipped, and accounts/transactions/budget still missing)."
    )
    ynab_import = HomeYnabImportSerializer()
    monthly_review_nudge = HomeMonthlyReviewNudgeSerializer(
        allow_null=True, help_text="Suggest reviewing last month; null when there is nothing to suggest."
    )
