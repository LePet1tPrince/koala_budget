"""
Forms for transactions app.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import ACCOUNT_TYPE_CHOICES, Account, AccountGroup, Payee


class AccountGroupForm(forms.ModelForm):
    """Form for creating and editing account groups."""

    class Meta:
        model = AccountGroup
        fields = ["name", "account_type", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class AccountForm(forms.ModelForm):
    """Form for creating and editing accounts with cascading account type and group selection."""

    # Add account_type as a non-model field for filtering account groups
    account_type = forms.ChoiceField(
        choices=[("", "---------")] + list(ACCOUNT_TYPE_CHOICES),
        required=True,
        label=_("Account Type"),
        help_text=_("Select account type to filter account groups"),
    )

    class Meta:
        model = Account
        fields = ["name", "account_number", "account_group", "has_feed"]

    # Define the field order explicitly
    field_order = ["name", "account_number", "account_type", "account_group", "has_feed"]

    def __init__(self, *args, **kwargs):
        team = kwargs.pop("team", None)
        super().__init__(*args, **kwargs)

        # If editing an existing account, set the account_type from the account_group
        if self.instance and self.instance.pk and self.instance.account_group:
            self.fields["account_type"].initial = self.instance.account_group.account_type

        # Filter account_group queryset based on selected account_type
        if team:
            account_type_value = None

            # Check if form was submitted with account_type data
            if self.data.get("account_type"):
                account_type_value = self.data.get("account_type")
            # Or if editing existing instance
            elif self.instance and self.instance.pk and self.instance.account_group:
                account_type_value = self.instance.account_group.account_type

            if account_type_value:
                # Filter account groups by the selected account type
                self.fields["account_group"].queryset = AccountGroup.for_team.filter(account_type=account_type_value)
            else:
                # Show all account groups (grouped by type in the label)
                self.fields["account_group"].queryset = AccountGroup.for_team.all()
                # Update help text to guide user
                self.fields["account_group"].help_text = _("Select an account type first for filtered options")

    def clean(self):
        """Validate that the selected account_group matches the selected account_type."""
        cleaned_data = super().clean()
        account_type = cleaned_data.get("account_type")
        account_group = cleaned_data.get("account_group")

        if account_type and account_group and account_group.account_type != account_type:
            raise forms.ValidationError(
                _("The selected account group '%(group)s' does not match the selected account type '%(type)s'.")
                % {
                    "group": account_group.name,
                    "type": dict(ACCOUNT_TYPE_CHOICES)[account_type],
                }
            )

        return cleaned_data


class PayeeForm(forms.ModelForm):
    """Form for creating and editing payees."""

    class Meta:
        model = Payee
        fields = ["name"]
