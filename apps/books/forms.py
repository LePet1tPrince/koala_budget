from django import forms
from django.utils.translation import gettext_lazy as _

from .helpers import reserved_book_slugs
from .models import Book

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
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError(_("Give the set of books a name."))
        clash = Book.objects.filter(team=self.team, name__iexact=name)
        if self.instance and self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(_("This team already has a set of books called %(name)s.") % {"name": name})
        return name


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
        fields = ["name", "slug", "budget_future_income"]
        labels = {"slug": _("Web address"), "budget_future_income": _("Budget income before it arrives")}
        help_texts = {
            "slug": _("The part of the address after the team. Changing it breaks links to the old one."),
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT, "maxlength": 100}),
            "slug": forms.TextInput(attrs={"class": INPUT + " font-mono", "maxlength": 50}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = self.instance.team

    def clean_slug(self):
        slug = self.cleaned_data["slug"].strip().lower()
        if slug in reserved_book_slugs():
            raise forms.ValidationError(
                _("%(slug)s is used by another page, so it can't be a book's address.") % {"slug": slug}
            )
        if Book.objects.filter(team=self.team, slug=slug).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Another set of books in this team already uses that address."))
        return slug


class ConfirmNameForm(forms.Form):
    """Type the book's name to confirm a destructive action."""

    confirm = forms.CharField(label=_("Type the name of the set of books to confirm"))

    def __init__(self, *args, book, **kwargs):
        self.book = book
        super().__init__(*args, **kwargs)
        self.fields["confirm"].widget.attrs.update({"class": INPUT, "autocomplete": "off"})

    def clean_confirm(self):
        value = self.cleaned_data["confirm"].strip()
        if value != self.book.name:
            raise forms.ValidationError(_("That isn't the name of this set of books."))
        return value
