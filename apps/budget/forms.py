# apps/budget/forms.py

from django import forms
from decimal import Decimal
from .models import Budget

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
