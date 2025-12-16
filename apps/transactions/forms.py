"""
Forms for transactions app.
"""

from django import forms

from .models import Account, AccountGroup, Payee


class AccountGroupForm(forms.ModelForm):
    """Form for creating and editing account groups."""

    class Meta:
        model = AccountGroup
        fields = ["name", "account_type", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class AccountForm(forms.ModelForm):
    """Form for creating and editing accounts."""

    class Meta:
        model = Account
        fields = ["name", "account_number", "account_type", "account_group", "has_feed"]

    def __init__(self, *args, **kwargs):
        team = kwargs.pop("team", None)
        super().__init__(*args, **kwargs)
        if team:
            # Filter account_group choices to only show groups from the current team
            self.fields["account_group"].queryset = AccountGroup.for_team.all()


class PayeeForm(forms.ModelForm):
    """Form for creating and editing payees."""

    class Meta:
        model = Payee
        fields = ["name"]

