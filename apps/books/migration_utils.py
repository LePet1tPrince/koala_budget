"""
Data steps shared by the migrations that move every financial row from its team
to a set of books (`docs/books-plan.md`, M3 and M6).

They take historical models from the migration's `apps`, never the live ones:
the live models no longer have a `team` column at all.
"""

from django.db.models import OuterRef, Subquery

# Every model that moved from `BaseTeamModel` to `BaseBookModel`.
BOOK_MODELS = [
    ("accounts", "accountgroup"),
    ("accounts", "account"),
    ("accounts", "institution"),
    ("accounts", "payee"),
    ("journal", "journalentry"),
    ("journal", "journalline"),
    ("budget", "budget"),
    ("budget", "goal"),
    ("budget", "goalallocation"),
    ("bank_feed", "banktransaction"),
    ("bank_feed", "transfermatchdismissal"),
    ("plaid", "plaiditem"),
    ("plaid", "plaidaccount"),
    ("plaid", "plaidtransaction"),
    ("reconciliation", "reconciliation"),
    ("monthly_review", "monthlyreviewstate"),
    ("onboarding", "onboardingstate"),
    ("portability", "dataimport"),
    ("ynab_import", "ynabimport"),
]

# Audit events that belong to the team rather than to its books.
TEAM_LEVEL_AUDIT_EVENTS = ("user_login", "user_logout", "login_failed", "team_member_added", "team_member_removed")


def default_book_subquery(apps):
    """The team's default book (first open by `sort_order`, then creation) for an `OuterRef("team_id")`."""
    Book = apps.get_model("books", "Book")
    return Subquery(
        Book.objects.filter(team_id=OuterRef("team_id"), is_archived=False)
        .order_by("sort_order", "id")
        .values("id")[:1]
    )


def fill_team_from_book(app_label, model_names):
    """A reverse step: put `team` back from `book`, before `team` is made required again."""

    def fill(apps, schema_editor):
        Book = apps.get_model("books", "Book")
        team_of_book = Subquery(Book.objects.filter(id=OuterRef("book_id")).values("team_id")[:1])
        for model_name in model_names:
            model = apps.get_model(app_label, model_name)
            model._base_manager.filter(team__isnull=True).update(team_id=team_of_book)

    return fill
