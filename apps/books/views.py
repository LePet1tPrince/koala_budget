import re
from datetime import date

from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponsePermanentRedirect, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import re_path, reverse
from django.utils.translation import gettext as _

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.teams.decorators import login_and_team_required, team_admin_required

from .decorators import book_admin_required
from .forms import (
    START_EXPORT,
    START_YNAB,
    BookBudgetingForm,
    BookCreateForm,
    BookSettingsForm,
    ConfirmNameForm,
)
from .helpers import create_book, remember_book, url_segments
from .models import Book

# --- Legacy URLs ------------------------------------------------------------------


def legacy_book_redirect_pattern(book_patterns, team_patterns):
    """
    The URL pattern that catches pre-books links (`/a/{team}/budget/...`).

    Only book-level app prefixes are caught, and never one a team-level page also
    uses (`settings`): those have their own page at the old address.
    """
    prefixes = sorted(url_segments(book_patterns) - url_segments(team_patterns))
    alternation = "|".join(re.escape(seg) for seg in prefixes)
    return re_path(
        rf"^a/(?P<team_slug>[-a-zA-Z0-9_]+)/(?P<legacy_prefix>{alternation})/(?P<rest>.*)$",
        legacy_book_redirect,
        name="legacy_book_redirect",
    )


@login_and_team_required
def legacy_book_redirect(request, team_slug, legacy_prefix, rest):
    """
    301 an old `/a/{team}/{prefix}/{rest}` to the same path under the team's
    default book, query string kept.

    Only reads are redirected: a POST to an old URL is an open tab from before
    the deploy, and replaying a write against a book the user never chose is not
    something to do silently.
    """
    if request.method not in ("GET", "HEAD"):
        raise Http404
    book = request.team.default_book
    if book is None:
        raise Http404
    url = f"/a/{team_slug}/{book.slug}/{legacy_prefix}/{rest}"
    if request.META.get("QUERY_STRING"):
        url = f"{url}?{request.META['QUERY_STRING']}"
    return HttpResponsePermanentRedirect(url)


# --- Team level -------------------------------------------------------------------


@login_and_team_required
def book_list(request, team_slug):
    """Every set of books in the team, archived ones included so they can be restored."""
    return render(
        request,
        "books/book_list.html",
        {
            "books": Book.objects.filter(team=request.team).order_by("is_archived", "sort_order", "name"),
            "active_tab": "settings",
            "settings_section": "books",
            "settings_page_title": _("Sets of books"),
            "page_title": _("Sets of books"),
            "settings_page_blurb": _(
                "Each set of books has its own accounts, transactions, budget and goals. "
                "Nothing is shared between them."
            ),
        },
    )


@team_admin_required
def book_create(request, team_slug):
    """
    Name a new set of books, then start it one of three ways: the onboarding
    questionnaire, the YNAB importer, or loading a Koala Budget export.
    """
    form = BookCreateForm(request.POST or None, team=request.team)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            book = create_book(request.team, form.cleaned_data["name"])
        log_event(
            AuditEvent.BOOK_CREATED,
            request=request,
            team=request.team,
            book=book,
            metadata={"name": book.name, "start": form.cleaned_data["start"]},
        )
        remember_book(request, book)
        start = form.cleaned_data["start"]
        if start == START_YNAB:
            return HttpResponseRedirect(reverse("ynab_import:home", args=book.url_args))
        if start == START_EXPORT:
            return HttpResponseRedirect(reverse("portability:home", args=book.url_args))
        # The book home sends an un-onboarded book into the walkthrough.
        return HttpResponseRedirect(reverse("onboarding:home", args=book.url_args))
    return render(
        request,
        "books/book_create.html",
        {
            "form": form,
            "page_title": _("New set of books"),
            "takeover_title": _("New set of books"),
            "takeover_eyebrow": request.team.name,
            "takeover_close_url": reverse("books_team:list", args=[team_slug]),
        },
    )


# --- Book level -------------------------------------------------------------------


@book_admin_required
def book_settings(request, team_slug, book_slug):
    book = request.book
    old_slug = book.slug
    form = BookSettingsForm(request.POST or None, instance=book)
    if request.method == "POST" and form.is_valid():
        book = form.save()
        messages.success(request, _("Saved."))
        if book.slug != old_slug:
            messages.info(request, _("The address changed. Links to the old one no longer work."))
        return HttpResponseRedirect(reverse("books:settings", args=book.url_args))
    return render(
        request,
        "books/book_settings.html",
        {
            "form": form,
            "active_tab": "settings",
            "settings_section": "book",
            "settings_page_title": _("This set of books"),
            "page_title": _("This set of books"),
            "settings_page_blurb": _("Its name and web address."),
        },
    )


def _unassigned_both_ways(book):
    """This month's Unassigned with the future-income setting as it is, and flipped."""
    from apps.budget.unassigned import compute_unassigned

    month = date.today().replace(day=1)
    current = compute_unassigned(book, month)
    flipped = compute_unassigned(book, month, future_income=not book.budget_future_income)
    return current, flipped


@book_admin_required
def book_budgeting(request, team_slug, book_slug):
    """
    The future-income setting. The page states the consequence before saving --
    what Unassigned would be this month with the setting flipped -- computed by
    the same function the pill uses, so the two cannot disagree.
    """
    book = request.book
    # Not `request.POST or None`: switching the setting off posts an empty form
    # (an unticked checkbox sends nothing), which must still bind.
    form = BookBudgetingForm(request.POST if request.method == "POST" else None, instance=book)
    # Read before validating: `is_valid()` copies the posted value onto the instance.
    before = book.budget_future_income
    if request.method == "POST" and form.is_valid():
        book = form.save()
        if before != book.budget_future_income:
            log_event(
                AuditEvent.BOOK_SETTINGS_CHANGED,
                request=request,
                team=request.team,
                book=book,
                metadata={"budget_future_income": book.budget_future_income},
            )
        messages.success(request, _("Saved."))
        return HttpResponseRedirect(reverse("books:budgeting", args=book.url_args))
    current, flipped = _unassigned_both_ways(book)
    return render(
        request,
        "books/book_budgeting.html",
        {
            "form": form,
            "unassigned_now": current,
            "unassigned_flipped": flipped,
            "active_tab": "settings",
            "settings_section": "budgeting",
            "settings_page_title": _("Budgeting"),
            "page_title": _("Budgeting"),
            "settings_page_blurb": _("How this set of books counts money that hasn't arrived yet."),
        },
    )


def _open_books(team):
    return Book.objects.filter(team=team, is_archived=False)


@book_admin_required
def book_archive(request, team_slug, book_slug):
    """
    Archive or delete this set of books. Both are refused for the team's last
    open book -- a team always has somewhere to land.
    """
    book = request.book
    is_last = not _open_books(request.team).exclude(pk=book.pk).exists()
    form = ConfirmNameForm(request.POST or None, book=book)
    if request.method == "POST":
        if is_last and not book.is_archived:
            messages.error(request, _("This is the team's only set of books, so it can't be archived."))
            return HttpResponseRedirect(reverse("books:archive", args=book.url_args))
        if form.is_valid():
            book.archive()
            log_event(AuditEvent.BOOK_ARCHIVED, request=request, team=request.team, book=book)
            messages.success(request, _("%(name)s was archived.") % {"name": book.name})
            return HttpResponseRedirect(reverse("books_team:list", args=[request.team.slug]))
    return render(
        request,
        "books/book_archive.html",
        {
            "form": form,
            "delete_form": ConfirmNameForm(book=book, prefix="delete"),
            "is_last": is_last,
            "active_tab": "settings",
            "settings_section": "archive",
            "settings_page_title": _("Archive or delete"),
            "page_title": _("Archive or delete"),
            "settings_page_blurb": _("Put this set of books away, or remove it and everything in it."),
        },
    )


@book_admin_required
def book_restore(request, team_slug, book_slug):
    if request.method != "POST":
        raise Http404
    book = request.book
    book.restore()
    log_event(AuditEvent.BOOK_RESTORED, request=request, team=request.team, book=book)
    messages.success(request, _("%(name)s was restored.") % {"name": book.name})
    return HttpResponseRedirect(reverse("web_book:home", args=book.url_args))


@book_admin_required
def book_delete(request, team_slug, book_slug):
    """Delete the book and every row in it. Type-the-name confirmed; never the last book."""
    if request.method != "POST":
        raise Http404
    from apps.portability.services.wipe import wipe_book

    book = get_object_or_404(Book, pk=request.book.pk)
    form = ConfirmNameForm(request.POST, book=book, prefix="delete")
    if not _open_books(request.team).exclude(pk=book.pk).exists():
        messages.error(request, _("This is the team's only set of books, so it can't be deleted."))
        return HttpResponseRedirect(reverse("books:archive", args=book.url_args))
    if not form.is_valid():
        messages.error(request, form.errors["confirm"][0])
        return HttpResponseRedirect(reverse("books:archive", args=book.url_args))

    name = book.name
    with transaction.atomic():
        wipe_book(book)
        # Audit rows outlive the book (their FK is SET_NULL); the event says which one it was.
        log_event(AuditEvent.BOOK_DELETED, request=request, team=request.team, book=None, metadata={"name": name})
        book.delete()
    messages.success(request, _("%(name)s was deleted.") % {"name": name})
    return HttpResponseRedirect(reverse("web_team:home", args=[request.team.slug]))
