from django import forms

from .models import Goal

class GoalForm(forms.ModelForm):
    """Form for creating and editing goals."""

    class Meta:
        model = Goal
        fields = ["name", "description", "goal_amount", "target_date", "saved_amount"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "target_date": forms.DateInput(attrs={"type": "date"}),
        }
