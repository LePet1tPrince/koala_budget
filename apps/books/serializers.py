from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.budget.unassigned import EXPECTED_INCOME_LABEL

from .forms import START_CHOICES, START_QUESTIONNAIRE
from .models import Book
from .services import unassigned_both_ways
from .validation import clean_book_name, clean_book_slug, clean_confirm_name, clean_locked_through


class BookSerializer(serializers.ModelSerializer):
    """
    A set of books as the team's book list shows it. `can_archive` / `can_delete`
    say whether the action is allowed at all (neither may leave the team without an
    open book); who may take it is the endpoint's (admins).

    Expects `open_count` (the team's open books) in the context; the viewset puts it there.
    """

    base_url = serializers.CharField(read_only=True, help_text="`/a/{team}/{book}/`, the prefix of its pages and API.")
    is_default = serializers.SerializerMethodField()
    can_archive = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = (
            "id",
            "name",
            "slug",
            "is_archived",
            "archived_at",
            "sort_order",
            "base_url",
            "is_default",
            "can_archive",
            "can_delete",
        )
        read_only_fields = fields

    def _others_open(self, book) -> bool:
        open_count = self.context["open_count"]
        return open_count - (0 if book.is_archived else 1) > 0

    def get_is_default(self, book) -> bool:
        return book.id == self.context.get("default_book_id")

    def get_can_archive(self, book) -> bool:
        return not book.is_archived and self._others_open(book)

    def get_can_delete(self, book) -> bool:
        return self._others_open(book)


class BookCreateSerializer(serializers.Serializer):
    """Name a new set of books and say how it will be started (the client opens that flow next)."""

    name = serializers.CharField(max_length=100)
    start = serializers.ChoiceField(choices=START_CHOICES, default=START_QUESTIONNAIRE)

    def validate_name(self, value):
        return clean_book_name(self.context["team"], value)


class BookConfirmSerializer(serializers.Serializer):
    """Type the book's name to confirm archiving or deleting it."""

    confirm = serializers.CharField(help_text="The book's name, exactly.")

    def validate_confirm(self, value):
        return clean_confirm_name(self.context["book"], value)


class FutureIncomePreviewSerializer(serializers.Serializer):
    """
    What the future-income setting does this month, either way: Unassigned is the
    same; Expected income is what it would be with the setting as saved and flipped.
    """

    month = serializers.DateField()
    unassigned = serializers.DecimalField(max_digits=15, decimal_places=2)
    expected_income_label = serializers.CharField()
    expected_income = serializers.DecimalField(max_digits=15, decimal_places=2)
    expected_income_flipped = serializers.DecimalField(max_digits=15, decimal_places=2)


class BookSettingsSerializer(serializers.ModelSerializer):
    """
    A book's own settings (`BookSettingsForm` on the web; the same rules, from
    `validation.py`). PATCH semantics: a field left out keeps its value;
    `locked_through: null` reopens every period.
    """

    base_url = serializers.CharField(read_only=True)
    future_income_preview = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = (
            "id",
            "name",
            "slug",
            "base_url",
            "budget_future_income",
            "locked_through",
            "future_income_preview",
        )
        read_only_fields = ("id", "base_url", "future_income_preview")
        extra_kwargs = {
            "slug": {
                "help_text": _("The part of the address after the team. Changing it breaks links to the old one.")
            },
            "locked_through": {
                "help_text": _(
                    "Transactions dated on or before this day can't be added, changed, voided or deleted. "
                    "Null keeps every period open. Budgets aren't affected."
                )
            },
        }

    def validate_name(self, value):
        return clean_book_name(self.instance.team, value, exclude_pk=self.instance.pk)

    def validate_slug(self, value):
        return clean_book_slug(self.instance.team, value, exclude_pk=self.instance.pk)

    def validate_locked_through(self, value):
        return clean_locked_through(value)

    @staticmethod
    def preview(book) -> dict:
        current, flipped = unassigned_both_ways(book)
        return {
            "month": current.month,
            "unassigned": current.amount,
            "expected_income_label": str(EXPECTED_INCOME_LABEL),
            # Zero whichever way the setting is off: no income is budgeted then.
            "expected_income": current.income_due,
            "expected_income_flipped": flipped.income_due,
        }

    @extend_schema_field(FutureIncomePreviewSerializer)
    def get_future_income_preview(self, book):
        return FutureIncomePreviewSerializer(self.preview(book)).data
