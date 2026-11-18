"""Response shapes of the user-level and chrome endpoints (`/api/me/`, `api/nav-state/`)."""

from rest_framework import serializers

from apps.budget.unassigned import STATE_NEGATIVE, STATE_POSITIVE, STATE_ZERO
from apps.teams.roles import ROLE_CHOICES

from .base import MonthField

# --- /api/me/ -------------------------------------------------------------------


class MeUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    display_name = serializers.CharField()
    avatar_url = serializers.CharField(help_text="Absolute URL of the uploaded avatar, else a Gravatar.")
    language = serializers.CharField(allow_null=True, help_text="Preferred UI language code; null = browser default.")
    timezone = serializers.CharField(allow_blank=True, help_text="IANA time zone name; blank = not set.")


class MeBookSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.SlugField()
    name = serializers.CharField()
    is_archived = serializers.BooleanField()
    is_default = serializers.BooleanField(help_text="The team's default book (its first open one).")
    base_url = serializers.CharField(help_text="`/a/{team}/{book}/`, the prefix of every URL in this book.")


class MeTeamSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.SlugField()
    name = serializers.CharField()
    role = serializers.ChoiceField(choices=ROLE_CHOICES)
    books = MeBookSerializer(many=True, help_text="Every book of the team, archived ones included, in sidebar order.")


class MeDefaultSerializer(serializers.Serializer):
    team = serializers.SlugField(help_text="Slug of the team the web app would open.")
    book = serializers.SlugField(allow_null=True, help_text="Slug of the book it would open; null if all are archived.")


class MeSerializer(serializers.Serializer):
    user = MeUserSerializer()
    teams = MeTeamSerializer(many=True)
    default = MeDefaultSerializer(allow_null=True, help_text="Where the web app lands at `/`; null with no team.")


# --- /a/{team}/{book}/api/nav-state/ ---------------------------------------------


class NavFeedAccountSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    is_bank_account = serializers.BooleanField(help_text="An asset (bank) account; false = a card or other liability.")


class NavFeedInstitutionSerializer(serializers.Serializer):
    name = serializers.CharField(allow_null=True, help_text="Institution name; null groups accounts with none.")
    accounts = NavFeedAccountSerializer(many=True)


class NavExpectedIncomeSerializer(serializers.Serializer):
    label = serializers.CharField()
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)


class NavUnassignedSerializer(serializers.Serializer):
    month = MonthField(help_text="Always the current month.")
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    state = serializers.ChoiceField(choices=[STATE_POSITIVE, STATE_ZERO, STATE_NEGATIVE])
    label = serializers.CharField(help_text="“Unassigned”, or “Over-assigned” when negative.")
    expected_income = NavExpectedIncomeSerializer(
        allow_null=True, help_text="Budgeted income not yet received; null unless the book budgets income ahead."
    )


class NavOnboardingRailSerializer(serializers.Serializer):
    visible = serializers.BooleanField(help_text="The guided task rail belongs on this book's pages.")


class NavStateSerializer(serializers.Serializer):
    inbox_count = serializers.IntegerField(help_text="Uncategorized bank transactions waiting in the Inbox.")
    feed_institutions = NavFeedInstitutionSerializer(many=True)
    unassigned = NavUnassignedSerializer()
    onboarding_rail = NavOnboardingRailSerializer()
