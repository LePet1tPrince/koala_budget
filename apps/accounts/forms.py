"""
Forms for accounts app.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import (
    ACCOUNT_TYPE_BUDGET,
    ACCOUNT_TYPE_CHOICES,
    Account,
    AccountGroup,
    Institution,
    Payee,
)
from .validators import (
    GROUP_TYPE_LOCKED_MESSAGE,
    account_group_type_error,
    account_name_error,
    group_type_locked,
    holds_institution,
    unique_name_error,
)


class BookUniqueNameMixin:
    """
    Enforce the model's `unique_together = ["book", "name"]` as a form error.

    `book` is not a form field, so ModelForm's own unique check skips the
    constraint and a duplicate name reached the database as an IntegrityError.
    """

    def __init__(self, *args, book=None, **kwargs):
        self.book = book
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.book is not None:
            error = unique_name_error(self._meta.model, self.book, name, self.instance)
            if error:
                raise forms.ValidationError(error)
        return name


class AccountGroupForm(BookUniqueNameMixin, forms.ModelForm):
    """Form for creating and editing account groups."""

    class Meta:
        model = AccountGroup
        fields = ["name", "account_type", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The model also knows the budget type; budget groups belong to the app.
        self.fields["account_type"].choices = [("", "---------"), *ACCOUNT_TYPE_CHOICES]
        # A group's type is its accounts' type (validators.group_type_locked).
        if group_type_locked(self.instance):
            field = self.fields["account_type"]
            field.disabled = True
            field.help_text = GROUP_TYPE_LOCKED_MESSAGE


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
        book = kwargs.pop("book", None)
        is_create = kwargs.pop("is_create", False)
        self.book = book
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

        # Filter account_group and institution querysets to the current book
        if book:
            if account_type_value:
                # Filter account groups by the selected account type
                self.fields["account_group"].queryset = AccountGroup.for_book.filter(account_type=account_type_value)
            else:
                # Show all account groups (grouped by type in the label)
                self.fields["account_group"].queryset = AccountGroup.for_book.exclude(account_type=ACCOUNT_TYPE_BUDGET)
                # Update help text to guide user
                self.fields["account_group"].help_text = _("Select an account type first for filtered options")

            self.fields["institution"].queryset = Institution.for_book.all()

        # Institution is only relevant for asset and liability accounts.
        # In create mode the unbound form keeps the field so the template can render
        # the options (Alpine.js toggles visibility); once a type is chosen, drop it
        # for non-asset/liability types so stray institution data is never saved.
        if not holds_institution(account_type_value) and (not is_create or account_type_value):
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

        error = account_group_type_error(account_group, account_type)
        if error:
            raise forms.ValidationError(error)

        if name and self.book and account_type:
            error = account_name_error(self.book, name, account_type, self.instance)
            if error:
                raise forms.ValidationError(error)

        return cleaned_data


class InstitutionForm(BookUniqueNameMixin, forms.ModelForm):
    """Form for creating and editing institutions."""

    class Meta:
        model = Institution
        fields = ["name"]


class PayeeForm(BookUniqueNameMixin, forms.ModelForm):
    """Form for creating and editing payees."""

    class Meta:
        model = Payee
        fields = ["name"]
