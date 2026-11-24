from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Book
from .validation import clean_book_name, clean_confirm_name, clean_locked_through

START_QUESTIONNAIRE = "questionnaire"
START_YNAB = "ynab"
START_EXPORT = "export"

START_CHOICES = [
    (START_QUESTIONNAIRE, _("Answer a few questions and we'll set up the accounts")),
    (START_YNAB, _("Import from YNAB")),
    (START_EXPORT, _("Load a Koala Budget export")),
]

INPUT = "input input-bordered w-full"


class BookNameMixin:
    """Book names are unique within a team, compared case-insensitively: "Business" and "business" clash."""

    def clean_name(self):
        exclude_pk = self.instance.pk if self.instance else None
        return clean_book_name(self.team, self.cleaned_data["name"], exclude_pk=exclude_pk)


class BookCreateForm(BookNameMixin, forms.ModelForm):
    start = forms.ChoiceField(
        label=_("How do you want to start?"),
        choices=START_CHOICES,
        initial=START_QUESTIONNAIRE,
        widget=forms.RadioSelect,
    )

    class Meta:
        model = Book
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"class": INPUT, "autofocus": True, "maxlength": 100})}

    def __init__(self, *args, team, **kwargs):
        self.team = team
        super().__init__(*args, **kwargs)


class BookSettingsForm(BookNameMixin, forms.ModelForm):
    class Meta:
        model = Book
        fields = ["name", "budget_future_income", "locked_through"]
        labels = {
            "budget_future_income": _("Budget income before it arrives"),
            "locked_through": _("Closed through"),
        }
        help_texts = {
            "locked_through": _(
                "Transactions dated on or before this day can't be added, changed, voided or deleted -- for "
                "example once a tax return for the period is filed. Leave blank to keep every period open. "
                "Budgets aren't affected."
            ),
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT, "maxlength": 100}),
            # A native date input (the no-JS path) that `date-field-mount.jsx` turns into the app's DateField.
            "locked_through": forms.DateInput(
                format="%Y-%m-%d",
                attrs={
                    "type": "date",
                    "class": INPUT + " max-w-48",
                    "data-date-field": "",
                    "data-allow-clear": "",
                    "data-testid": "locked-through-input",
                },
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = self.instance.team

    def clean_locked_through(self):
        # A post that leaves the field out keeps the saved lock; a blank one clears it.
        if self.add_prefix("locked_through") not in self.data:
            return self.instance.locked_through
        return clean_locked_through(self.cleaned_data.get("locked_through"))


class ConfirmNameForm(forms.Form):
    """Type the book's name to confirm a destructive action."""

    confirm = forms.CharField(label=_("Type the name of the set of books to confirm"))

    def __init__(self, *args, book, **kwargs):
        self.book = book
        super().__init__(*args, **kwargs)
        self.fields["confirm"].widget.attrs.update({"class": INPUT, "autocomplete": "off"})

    def clean_confirm(self):
        return clean_confirm_name(self.book, self.cleaned_data["confirm"])
