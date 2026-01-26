# apps/budget/forms.py

from decimal import Decimal

from django import forms

from .models import Budget, Goal, GoalAllocation


class BudgetAmountForm(forms.ModelForm):
    budget_amount = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            "step": "0.01",
            "class": "budget-input",
        })
    )

    class Meta:
        model = Budget
        fields = ["budget_amount"]

    def clean_budget_amount(self):
        """Convert blank/empty values to 0."""
        value = self.cleaned_data.get('budget_amount')
        if value is None or value == '':
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


class GoalAllocationForm(forms.ModelForm):
    """Form for editing goal allocations inline."""

    class Meta:
        model = GoalAllocation
        fields = ["amount"]
        widgets = {
            "amount": forms.NumberInput(attrs={
                "class": "input input-bordered input-sm w-24 text-right font-mono",
                "step": "0.01",
                "min": "0",
            }),
        }

    def clean_amount(self):
        """Convert blank/empty values to 0."""
        value = self.cleaned_data.get("amount")
        if value is None or value == "":
            return Decimal("0")
        return value
