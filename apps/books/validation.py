"""
The rules a book's name, address, closed period and type-the-name confirmations
follow, in one place for the two callers that enforce them: the Django forms
(`forms.py`, the server-rendered pages) and the DRF serializers (`serializers.py`,
the API). Each raises Django's `ValidationError`; a form turns it into a field
error, and DRF's `Serializer.to_internal_value` does the same for a
`validate_<field>` method that calls one.
"""

from datetime import date

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from .helpers import reserved_book_slugs
from .models import Book


def clean_book_name(team, name: str, *, exclude_pk=None) -> str:
    """Book names are unique within a team, compared case-insensitively: "Business" and "business" clash."""
    name = (name or "").strip()
    if not name:
        raise ValidationError(_("Give the set of books a name."))
    clash = Book.objects.filter(team=team, name__iexact=name)
    if exclude_pk:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        raise ValidationError(_("This team already has a set of books called %(name)s.") % {"name": name})
    return name


def clean_book_slug(team, slug: str, *, exclude_pk=None) -> str:
    """A book's address: not a reserved first segment, and free within its team."""
    slug = (slug or "").strip().lower()
    if slug in reserved_book_slugs():
        raise ValidationError(_("%(slug)s is used by another page, so it can't be a book's address.") % {"slug": slug})
    if Book.objects.filter(team=team, slug=slug).exclude(pk=exclude_pk).exists():
        raise ValidationError(_("Another set of books in this team already uses that address."))
    return slug


def clean_locked_through(value: date | None) -> date | None:
    """The closed period's last day: blank reopens every period; only a day that has passed can close one."""
    if value is not None and value > date.today():
        raise ValidationError(_("Only a period that has already ended can be closed."))
    return value


def clean_confirm_name(book, value: str) -> str:
    """Type the book's name to confirm a destructive action (archive, delete)."""
    value = (value or "").strip()
    if value != book.name:
        raise ValidationError(_("That isn't the name of this set of books."))
    return value
