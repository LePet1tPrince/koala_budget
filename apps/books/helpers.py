from functools import cache

from django.db.models import Max
from django.http import Http404
from django.urls import URLResolver
from django.utils.text import slugify

from apps.utils.slug import get_next_slug

from .models import DEFAULT_BOOK_NAME, DEFAULT_BOOK_SLUG, Book

# Session keys. `book` is the last book opened anywhere; `book_by_team` is the
# last one opened in each team, so switching teams lands on the right book.
SESSION_BOOK = "book"
SESSION_BOOK_BY_TEAM = "book_by_team"


@cache
def reserved_book_slugs() -> frozenset[str]:
    """
    The slugs a book may not take, read off the URLconf rather than written out.

    Team-level pages share the `/a/{team}/` prefix with books, so a book called
    `settings` would shadow the team's settings page. Book-level app prefixes are
    reserved too: that is what lets the legacy redirect tell an old
    `/a/{team}/budget/` link from a book called "budget". Deriving the list means
    a new prefix is reserved the moment it is mounted.
    """
    from koala_budget.urls import book_urlpatterns, team_level_urlpatterns

    return frozenset(url_segments(team_level_urlpatterns)) | frozenset(url_segments(book_urlpatterns))


def url_segments(patterns) -> set[str]:
    """
    The first path segments a list of URL patterns claims. An include mounted at
    "" contributes its own patterns' segments (the team level's `settings/` comes
    from the web app's include at the team root).
    """
    segments = set()
    for pattern in patterns:
        route = str(pattern.pattern)
        if route == "" and isinstance(pattern, URLResolver):
            segments |= url_segments(pattern.url_patterns)
        elif segment := route.split("/")[0]:
            segments.add(segment)
    return segments


def unique_book_slug(team, name: str, exclude_pk=None) -> str:
    """A slug for `name` that is free within `team` and not reserved."""
    base = slugify(name)[:40] or "book"
    taken = set(Book.objects.filter(team=team).exclude(pk=exclude_pk).values_list("slug", flat=True))
    taken |= reserved_book_slugs()
    slug, suffix = base, 2
    while slug in taken:
        slug = get_next_slug(base, suffix, max_length=50)
        suffix += 1
    return slug


def create_book(team, name: str, **fields) -> Book:
    """Create a book in `team` with a slug derived from its name."""
    sort_order = fields.pop("sort_order", None)
    if sort_order is None:
        last = Book.objects.filter(team=team).aggregate(last=Max("sort_order"))["last"]
        sort_order = 0 if last is None else last + 1
    return Book.objects.create(team=team, name=name, slug=unique_book_slug(team, name), sort_order=sort_order, **fields)


def ensure_default_book(team) -> Book:
    """The team's default book, creating the standard "Personal" one if it has none."""
    book = team.default_book
    if book is None:
        book, _ = Book.objects.get_or_create(
            team=team, slug=DEFAULT_BOOK_SLUG, defaults={"name": DEFAULT_BOOK_NAME, "sort_order": 0}
        )
    return book


def get_book_for_request(request, view_kwargs) -> Book | None:
    """
    The book named by the URL, looked up *within* the URL's team.

    A book of another team is a 404 even to someone who belongs to both: the team
    in the URL is the one access was checked against.
    """
    book_slug = view_kwargs.get("book_slug")
    if not book_slug:
        return None
    team = getattr(request, "team", None)
    if not team:
        raise Http404
    try:
        return Book.objects.select_related("team").get(team=team, slug=book_slug)
    except Book.DoesNotExist:
        raise Http404 from None


def remember_book(request, book: Book):
    """Record `book` as the last one opened, overall and within its team."""
    session = getattr(request, "session", None)
    if session is None:
        return
    by_team = dict(session.get(SESSION_BOOK_BY_TEAM) or {})
    if session.get(SESSION_BOOK) != book.id or by_team.get(str(book.team_id)) != book.id:
        by_team[str(book.team_id)] = book.id
        session[SESSION_BOOK] = book.id
        session[SESSION_BOOK_BY_TEAM] = by_team


def last_book_for_team(request, team) -> Book | None:
    """The book this user last opened in `team`, else the team's default book."""
    if not team:
        return None
    session = getattr(request, "session", None)
    book_id = (session.get(SESSION_BOOK_BY_TEAM) or {}).get(str(team.id)) if session is not None else None
    if book_id:
        book = Book.objects.select_related("team").filter(id=book_id, team=team, is_archived=False).first()
        if book:
            return book
    return team.default_book


def get_nav_book(request) -> Book | None:
    """
    The book the chrome -- sidebar, switcher, pill -- should point at.

    `request.book` on a book page; on a team-level page (members, subscription)
    or an account page (profile) it is the book last opened in the nav team, so
    the sidebar stays whole. Page *content* must keep using `request.book`.
    """
    # `or None` resolves a lazy object wrapping None into a real None, so callers
    # can test the result with `is None`.
    return getattr(request, "book", None) or getattr(request, "default_book", None) or None


def team_has_several_books(team) -> bool:
    return Book.objects.filter(team=team, is_archived=False).count() > 1


def book_display_name(book) -> str:
    """
    How a page title names where the user is: just the team while it has one set
    of books (nothing changes for a single-book team), "Team · Book" once it has
    several.
    """
    if book is None:
        return ""
    if team_has_several_books(book.team):
        return f"{book.team.name} · {book.name}"
    return book.team.name


def nav_book_for_member(request) -> Book | None:
    """
    `get_nav_book`, for the context processors that put book data in the chrome
    (inbox count, feed accounts, the Unassigned pill, the task rail): None unless
    the user is signed in and -- when the URL names a team -- a member of it.
    `default_team` is already membership-checked; a URL team only is once the
    membership lookup finds a row.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None
    if getattr(request, "team", None) and not getattr(request, "team_membership", None):
        return None
    return get_nav_book(request)
