# apps/budget/forms.py

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import forms

from .models import Budget, Goal

# budget_amount is max_digits=15 / decimal_places=2, so 13 integer digits
MAX_BUDGET_AMOUNT = Decimal("9999999999999.99")


def parse_budget_amount(value):
    """Parse a typed budget amount, or None if it isn't a usable number.

    Tolerates what people actually paste out of a spreadsheet: "$1,234.56",
    "(45.50)" for a negative, a Unicode minus, stray whitespace. Blank means
    zero, which is how a row is cleared.
    """
    if isinstance(value, Decimal):
        return value
    text = str(value if value is not None else "").strip()
    if not text:
        return Decimal("0.00")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = text.replace("$", "").replace(",", "").replace("\u2212", "-").strip()
    if not text:
        return Decimal("0.00")
    try:
        amount = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite() or abs(amount) > MAX_BUDGET_AMOUNT:
        return None
    return -amount if negative else amount


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

    class Meta:
        model = Goal
        fields = ["name", "description", "target_amount", "target_date"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "description": forms.Textarea(attrs={"class": "textarea textarea-bordered w-full", "rows": 3}),
            "target_amount": forms.NumberInput(attrs={"class": "input input-bordered w-full", "step": "0.01"}),
            "target_date": forms.DateInput(attrs={"class": "input input-bordered w-full", "type": "date"}),
        }
