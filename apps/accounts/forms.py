"""
Forms for accounts app.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_CHOICES,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
    Institution,
    Payee,
)


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
        fields = ["name", "account_group", "institution", "has_feed"]

    # Define the field order explicitly
    field_order = ["name", "account_type", "account_group", "institution", "has_feed"]

    def __init__(self, *args, **kwargs):
        team = kwargs.pop("team", None)
        is_create = kwargs.pop("is_create", False)
        self.team = team
        super().__init__(*args, **kwargs)

        # If editing an existing account, set the account_type from the account_group
        if self.instance and self.instance.pk and self.instance.account_group:
            self.fields["account_type"].initial = self.instance.account_group.account_type

        # Determine effective account_type for conditional field display
        account_type_value = None
        if self.data.get("account_type"):
            account_type_value = self.data.get("account_type")
        elif self.instance and self.instance.pk and self.instance.account_group:
            account_type_value = self.instance.account_group.account_type

        # Make institution optional
        self.fields["institution"].required = False
        self.fields["institution"].empty_label = "---------"

        # Filter account_group and institution querysets to the current team
        if team:
            if account_type_value:
                # Filter account groups by the selected account type
                self.fields["account_group"].queryset = AccountGroup.for_team.filter(account_type=account_type_value)
            else:
                # Show all account groups (grouped by type in the label)
                self.fields["account_group"].queryset = AccountGroup.for_team.all()
                # Update help text to guide user
                self.fields["account_group"].help_text = _("Select an account type first for filtered options")

            self.fields["institution"].queryset = Institution.for_team.all()

        # Institution is only relevant for asset and liability accounts.
        # In create mode the unbound form keeps the field so the template can render
        # the options (Alpine.js toggles visibility); once a type is chosen, drop it
        # for non-asset/liability types so stray institution data is never saved.
        if account_type_value not in (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY) and (
            not is_create or account_type_value
        ):
            self.fields.pop("institution", None)

        # In create view, has_feed is automatically determined from account type
        if is_create:
            self.fields.pop("has_feed", None)

    def clean(self):
        """Validate account_group/account_type match and uniqueness of name within account type."""
        cleaned_data = super().clean()
        account_type = cleaned_data.get("account_type")
        account_group = cleaned_data.get("account_group")
        name = cleaned_data.get("name")

        if account_type and account_group and account_group.account_type != account_type:
            raise forms.ValidationError(
                _("The selected account group '%(group)s' does not match the selected account type '%(type)s'.")
                % {
                    "group": account_group.name,
                    "type": dict(ACCOUNT_TYPE_CHOICES)[account_type],
                }
            )

        if name and self.team and account_type:
            qs = Account.objects.filter(team=self.team, name=name, account_group__account_type=account_type)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    _("An account named '%(name)s' already exists for account type '%(type)s'.")
                    % {"name": name, "type": dict(ACCOUNT_TYPE_CHOICES)[account_type]}
                )

        return cleaned_data


class InstitutionForm(forms.ModelForm):
    """Form for creating and editing institutions."""

    class Meta:
        model = Institution
        fields = ["name"]


class PayeeForm(forms.ModelForm):
    """Form for creating and editing payees."""

    class Meta:
        model = Payee
        fields = ["name"]
