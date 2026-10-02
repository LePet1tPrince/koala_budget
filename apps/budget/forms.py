# apps/budget/forms.py

from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.utils.amounts import evaluate_amount

from .models import Budget, Goal

# budget_amount is max_digits=15 / decimal_places=2, so 13 integer digits
MAX_BUDGET_AMOUNT = Decimal("9999999999999.99")


def parse_budget_amount(value):
    """Parse a typed budget amount, or None if it isn't a usable number.

    Tolerates what people actually paste out of a spreadsheet: "$1,234.56",
    "(45.50)" for a negative, a Unicode minus, stray whitespace -- and simple
    arithmetic ("120+35", "3*19.99"), which the page's JS evaluates first but
    the <noscript> path posts as typed. Blank means zero, which is how a row is
    cleared.
    """
    if isinstance(value, Decimal):
        return value
    text = str(value if value is not None else "").strip()
    if not text.strip("$()"):
        return Decimal("0.00")
    amount = evaluate_amount(text)
    if amount is None or abs(amount) > MAX_BUDGET_AMOUNT:
        return None
    return amount


class AmountFormulaField(forms.DecimalField):
    """Decimal field that also accepts simple arithmetic ("250*12"), for the
    no-JS path of an amount field whose JS evaluates formulas on the page."""

    def to_python(self, value):
        if value in self.empty_values:
            return super().to_python(value)
        parsed = evaluate_amount(value)
        if parsed is None:
            return super().to_python(value)
        return parsed


class GroupedAmountInput(forms.TextInput):
    """Text input that renders a stored amount with thousands separators
    ("5,000.00"); the page's `data-amount-format` keeps typed values that way."""

    def format_value(self, value):
        if isinstance(value, (Decimal, int, float)):
            return f"{Decimal(value):,.2f}"
        return super().format_value(value)


class BudgetAmountField(forms.DecimalField):
    """Decimal field that accepts the same input as the budget table's auto-save,
    so the <noscript> fallback isn't stricter than the JS path."""

    def to_python(self, value):
        parsed = parse_budget_amount(value)
        if parsed is None:
            # Not a number at all — let DecimalField raise its own message.
            return super().to_python(value)
        return parsed


class BudgetAmountForm(forms.ModelForm):
    # A text input rather than a number input: the budget table binds Up/Down to
    # move between rows, which a number input would spend on its own spinner.
    budget_amount = BudgetAmountField(
        max_digits=15,
        decimal_places=2,
        required=False,
        widget=forms.TextInput(
            attrs={
                "inputmode": "decimal",
                "autocomplete": "off",
                "data-amount-input": "",
                "placeholder": "0.00",
                "class": "input input-bordered input-sm w-28 text-right font-mono",
            }
        ),
    )

    class Meta:
        model = Budget
        fields = ["budget_amount"]

    def clean_budget_amount(self):
        """Convert blank/empty values to 0."""
        value = self.cleaned_data.get("budget_amount")
        if value is None or value == "":
            return Decimal("0")
        return value


class GoalForm(forms.ModelForm):
    """Form for creating and editing goals."""

    target_amount = AmountFormulaField(
        max_digits=15,
        decimal_places=2,
        label=_("Target amount"),
        help_text=_("Target savings amount"),
        widget=GroupedAmountInput(
            attrs={
                "inputmode": "decimal",
                "autocomplete": "off",
                "data-amount-input": "",
                "data-amount-format": "",
                "class": "input input-bordered w-full",
            }
        ),
    )

    monthly_contribution = AmountFormulaField(
        max_digits=15,
        decimal_places=2,
        required=False,
        min_value=0,
        label=_("Monthly contribution"),
        help_text=_("How much you plan to put towards the goal each month"),
        widget=GroupedAmountInput(
            attrs={
                "inputmode": "decimal",
                "autocomplete": "off",
                "data-amount-input": "",
                "data-amount-format": "",
                "class": "input input-bordered w-full",
                "data-testid": "goal-monthly-input",
            }
        ),
    )

    class Meta:
        model = Goal
        fields = ["name", "description", "target_amount", "target_date", "monthly_contribution", "outflow"]
        widgets = {
            "outflow": forms.RadioSelect(attrs={"class": "radio radio-sm radio-primary"}),
            "name": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "description": forms.Textarea(attrs={"class": "textarea textarea-bordered w-full", "rows": 3}),
            # The native input is the no-JS path; `date-field` swaps in the app's DateField.
            "target_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={
                    "class": "input input-bordered w-full",
                    "type": "date",
                    "data-date-field": "",
                    "data-allow-clear": "",
                },
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only meaningful with a linked account; a form without the choice keeps
        # what the goal has (the model default for a new one).
        self.fields["outflow"].required = False

    def clean_outflow(self):
        return self.cleaned_data.get("outflow") or self.instance.outflow or Goal.OUTFLOW_WITHDRAW
