from django import forms

from .models import EmailPreferences

CHECKBOX = {"class": "checkbox checkbox-primary"}


class EmailPreferencesForm(forms.ModelForm):
    class Meta:
        model = EmailPreferences
        fields = ("bank_connection_alerts", "budget_alerts")
        widgets = {
            "bank_connection_alerts": forms.CheckboxInput(attrs={**CHECKBOX, "data-testid": "pref-bank-connection"}),
            "budget_alerts": forms.CheckboxInput(attrs={**CHECKBOX, "data-testid": "pref-budget"}),
        }
