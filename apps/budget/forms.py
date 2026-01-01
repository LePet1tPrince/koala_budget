# apps/budget/forms.py

from django import forms
from .models import Budget

class BudgetAmountForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ["budget_amount"]
        widgets = {
            "budget_amount": forms.NumberInput(attrs={
                "step": "0.01",
                "class": "budget-input",
            })
        }
