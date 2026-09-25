"""
Cross-book isolation (docs/books-plan.md §9), the backbone of the query sweep.

Two sets of books in one team, each with a full set of data. Under book A:

* every page and API lists none of book B's rows (READS);
* every object URL asked for with one of book B's ids is a 404 (OBJECTS);
* every write that names book B's rows leaves book B exactly as it was (WRITES).

The tables are parameterised over URL *names*, and `test_every_book_url_is_covered`
walks the book URLconf: a new endpoint fails the suite until it is placed in one of
them (or exempted, with a reason).
"""

import io
import json
import zipfile

from django.test import TestCase
from django.urls import URLResolver, reverse

from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

from .factories import build_book_data, second_book, snapshot

MARK_A = "QQALPHAQQ"
MARK_B = "QQBRAVOQQ"


def month_query(**extra):
    return {"month": "2026-03-01", **extra}


# name -> query params (a callable taking (a, b) BookData, or a dict)
READS = {
    "web_book:home": {},
    "books:settings": {},
    "accounts:accounts_home": {},
    "accounts:accountgroup_list": {},
    "accounts:payee_list": {},
    "accounts:institution_list": {},
    "journal:transactions_home": {},
    "journal:journal-entry-list": {},
    "journal:line-list": lambda a, b: {"account": b.groceries.id},
    "journal:transaction-list": {},
    "journal:transaction-facets": {"column": "payee"},
    "journal:api-root": {},
    "audit:audit-event-list": {},
    "audit:api-root": {},
    "audit:audit_log": {},
    "budget:budget_home": month_query(),
    "budget:budget_grid": {"start": "2026-01-01"},
    "budget:api_unassigned": {},
    "budget:goals_list": month_query(),
    "reports:reports_home": {},
    "reports:income_statement": {"start_date": "2026-03-01", "end_date": "2026-03-31"},
    "reports:balance_sheet": {"as_of_date": "2026-03-31"},
    "reports:net_worth_trend": {"start_month": "2026-01", "end_month": "2026-06"},
    "reports:cash_flow": {"start_month": "2026-01", "end_month": "2026-06"},
    "reports:budget_vs_actual": {"month": "2026-03"},
    "reports:goal_progress": {},
    "reports:dollar_map": {"month": "2026-03"},
    "reports:export_income_statement": {"start_date": "2026-03-01", "end_date": "2026-03-31"},
    "reports:export_balance_sheet": {"as_of_date": "2026-03-31"},
    "reports:export_transactions": {"start_date": "2026-03-01", "end_date": "2026-03-31"},
    "monthly_review:home": month_query(),
    "monthly_review:export": month_query(),
    "plaid:plaid-item-list": {},
    "plaid:plaid-account-list": {},
    "plaid:imported-transaction-list": {},
    "plaid:api-root": {},
    "bank_feed:bank_feed_home": {},
    "bank_feed:categorize_mode": lambda a, b: {"account": b.chequing.id},
    "bank_feed:bank-feed-list": lambda a, b: {"account": b.chequing.id},
    "bank_feed:bank-feed-account-groups": {},
    "bank_feed:bank-feed-category-suggestions": {},
    "bank_feed:bank-feed-feed-accounts": {},
    "bank_feed:bank-feed-sample-csv": {},
    "bank_feed:bank-feed-similar-categories": lambda a, b: {"ids": f"{b.uncategorized_tx.id},{a.uncategorized_tx.id}"},
    "bank_feed:bank-feed-transfer-suggestions": {},
    "bank_feed:api-root": {},
    "onboarding:home": {},
    "onboarding:api_tasks": {},
    "onboarding:api_opening_balances": {},
    "ynab_import:home": {},
    "portability:home": {},
    "portability:export": {},
    "reconciliation:hub": {},
    "reconciliation:reconciliation-list": lambda a, b: {"account": b.savings.id},
    "reconciliation:reconciliation-accounts": {},
    "reconciliation:api-root": {},
    "accounts:accountgroup_create": {},
    "accounts:account_create": {},
    "accounts:payee_create": {},
    "accounts:institution_create": {},
    "budget:goal_create": {},
}

# Looked up by an id in the query string rather than the path: B's id is a 404.
QUERY_OBJECTS = {
    "ynab_import:api_status": lambda b: {"import_id": b.ynab_import.id},
    "portability:api_status": lambda b: {"import_id": b.data_import.id},
}

# name -> (kind of B's object passed as the URL kwarg, kwarg name, method)
OBJECTS = {
    "accounts:accountgroup_detail": ("group", "pk", "get"),
    "accounts:accountgroup_update": ("group", "pk", "get"),
    "accounts:accountgroup_delete": ("group", "pk", "post"),
    "accounts:account_detail": ("account", "pk", "get"),
    "accounts:account_update": ("account", "pk", "get"),
    "accounts:account_delete": ("account", "pk", "post"),
    "accounts:payee_detail": ("payee", "pk", "get"),
    "accounts:payee_update": ("payee", "pk", "get"),
    "accounts:payee_delete": ("payee", "pk", "post"),
    "accounts:institution_detail": ("institution", "pk", "get"),
    "accounts:institution_update": ("institution", "pk", "get"),
    "accounts:institution_delete": ("institution", "pk", "post"),
    "journal:journal-entry-detail": ("entry", "pk", "get"),
    "journal:journal-entry-audit": ("entry", "pk", "get"),
    "journal:journal-entry-post-entry": ("entry", "pk", "post"),
    "journal:journal-entry-void-entry": ("entry", "pk", "post"),
    "journal:line-detail": ("line", "pk", "get"),
    "journal:transaction-detail": ("entry", "pk", "get"),
    "journal:line-recategorize": ("line", "pk", "post"),
    "audit:audit-event-detail": ("event", "pk", "get"),
    "budget:goal_detail": ("goal", "pk", "get"),
    "budget:goal_update": ("goal", "pk", "get"),
    "budget:goal_delete": ("goal", "pk", "post"),
    "budget:goal_allocate": ("goal", "pk", "post"),
    "budget:goal_assign_available": ("goal", "pk", "post"),
    "budget:goal_withdraw": ("goal", "pk", "post"),
    "budget:goal_complete": ("goal", "pk", "post"),
    "budget:goal_close": ("goal", "pk", "post"),
    "reports:account_activity": ("account", "account_id", "get"),
    "reports:export_account_activity": ("account", "account_id", "get"),
    "plaid:plaid-item-detail": ("plaid_item", "pk", "get"),
    "plaid:plaid-item-sync": ("plaid_item", "pk", "post"),
    "plaid:plaid-account-detail": ("plaid_account", "pk", "get"),
    "plaid:imported-transaction-detail": ("plaid_transaction", "pk", "get"),
    "bank_feed:bank-feed-detail": ("bank_transaction", "pk", "put"),
    "reconciliation:account": ("asset_account", "account_id", "get"),
    "reconciliation:statement": ("reconciliation", "pk", "get"),
    "reconciliation:statement_undo": ("reconciliation", "pk", "post"),
    "reconciliation:reconciliation-detail": ("reconciliation", "pk", "get"),
    "reconciliation:reconciliation-finish": ("reconciliation", "pk", "post"),
    "reconciliation:reconciliation-tick": ("reconciliation", "pk", "post"),
    "reconciliation:reconciliation-tick-through": ("reconciliation", "pk", "post"),
    "reconciliation:reconciliation-undo": ("reconciliation", "pk", "post"),
    "reconciliation:reconciliation-untick-all": ("reconciliation", "pk", "post"),
}

# name -> JSON body naming book B's rows (a callable taking (a, b) BookData).
# The request may succeed on book A or be refused; book B must not change.
WRITES = {
    "accounts:api_reorder_accounts": lambda a, b: {
        "groups": [{"group_id": b.expense_group.id, "account_ids": [b.groceries.id]}]
    },
    "accounts:api_reorder_groups": lambda a, b: {"account_type": "expense", "group_ids": [b.expense_group.id]},
    "accounts:api_create_account": lambda a, b: {"name": "Sneaky", "group_id": b.expense_group.id},
    "accounts:api_create_group": lambda a, b: {"name": "New group", "account_type": "expense"},
    "accounts:api_set_feed": lambda a, b: {"account_id": b.chequing.id, "has_feed": False},
    "journal:journal-entry-list": None,  # placeholder, see WRITE_OVERRIDES
    # The Transactions page's editor. Every write takes a list of ids, so book B's
    # entry is named the same way a selection would name it.
    "journal:transaction-edit": lambda a, b: {"ids": [b.entry.id], "description": "moved"},
    "journal:transaction-batch-delete": lambda a, b: {"ids": [b.entry.id]},
    "journal:transaction-batch-status": lambda a, b: {"ids": [b.entry.id], "status": "void"},
    "budget:budget_save_amount": lambda a, b: {"category_id": b.groceries.id, "month": "2026-03-01", "amount": "999"},
    "budget:budget_grid_save": lambda a, b: {
        "changes": [{"category_id": b.groceries.id, "month": "2026-03-01", "amount": "999"}]
    },
    # Book A's category covered from book B's goal: the goal is the row that must not move.
    # (B's category from Unassigned is BudgetCoverIsolationTest's.)
    "budget:budget_cover": lambda a, b: {
        "category_id": a.groceries.id,
        "month": "2026-03-01",
        "amount": "10",
        "source": "goal",
        "goal_id": b.goal.id,
    },
    "monthly_review:api_step": lambda a, b: {"month": "2026-03-01", "step": 2},
    "monthly_review:api_complete": lambda a, b: {"month": "2026-03-01"},
    "monthly_review:api_dismiss": lambda a, b: {"month": "2026-03-01"},
    "bank_feed:bank-feed-batch-archive": lambda a, b: {"ids": [b.categorized_tx.id]},
    "bank_feed:bank-feed-batch-unarchive": lambda a, b: {"ids": [b.categorized_tx.id]},
    "bank_feed:bank-feed-batch-delete": lambda a, b: {"ids": [b.categorized_tx.id]},
    "bank_feed:bank-feed-batch-duplicate": lambda a, b: {"ids": [b.categorized_tx.id]},
    "bank_feed:bank-feed-batch-unreconcile": lambda a, b: {"ids": [b.categorized_tx.id]},
    "bank_feed:bank-feed-batch-edit": lambda a, b: {"ids": [b.categorized_tx.id], "category_id": a.groceries.id},
    "bank_feed:bank-feed-categorize": lambda a, b: {
        "rows": [{"id": b.uncategorized_tx.id}],
        "category_id": b.groceries.id,
    },
    "bank_feed:bank-feed-create-account": lambda a, b: {"name": "Sneaky", "account_group_id": b.expense_group.id},
    "bank_feed:bank-feed-transfer-resolve": lambda a, b: {
        "archive_id": b.uncategorized_tx.id,
        "keep_id": b.other_tx.id,
    },
    "bank_feed:bank-feed-transfer-dismiss": lambda a, b: {
        "transaction_a": b.uncategorized_tx.id,
        "transaction_b": b.categorized_tx.id,
    },
    "bank_feed:bank-feed-upload-preview": lambda a, b: {"account_id": b.chequing.id},
    "bank_feed:bank-feed-upload-confirm": lambda a, b: {"account_id": b.chequing.id, "transactions": "[]"},
    "onboarding:api_answers": lambda a, b: {"answers": {"housing": "rent"}},
    "onboarding:api_preview_coa": lambda a, b: {"answers": {}},
    "onboarding:api_complete": lambda a, b: {"answers": {}},
    "onboarding:api_task": lambda a, b: {"slug": "net_worth"},
    "onboarding:api_skip": lambda a, b: {},
    "reconciliation:reconciliation-list": None,  # placeholder, see WRITE_OVERRIDES
}

# Endpoints whose body names B's accounts in nested structures; also their
# names are already in READS, so these run from dedicated tests below.
WRITE_OVERRIDES = {"journal:journal-entry-list", "reconciliation:reconciliation-list"}

EXEMPT = {
    "budget:budget_autofill": "form post over this book's own categories; BudgetFallbackTest covers B's ids",
    "plaid:create-link-token": "calls the Plaid API; creates nothing",
    "plaid:exchange-public-token": "calls the Plaid API; writes only to request.book",
    "bank_feed:bank-feed-upload-parse": "parses an uploaded file; reads no rows and writes none",
    "bank_feed:bank-feed-upload-validate-dates": "parses an uploaded file; reads no rows and writes none",
    "ynab_import:api_upload": "file-driven; the record is created on request.book (ynab TeamScopingTest)",
    "ynab_import:api_preview": "record looked up by book (ynab TeamScopingTest)",
    "ynab_import:api_apply": "record looked up by book (ynab TeamScopingTest)",
    "portability:api_upload": "file-driven; the record is created on request.book",
    "portability:api_apply": "record looked up by book; the wipe is wipe_book (WipeBookTest)",
    "portability:api_safety_export": "record looked up by book, like api_status",
}


def book_url_names():
    """Every named URL mounted under /a/{team}/{book}/."""
    from koala_budget.urls import book_urlpatterns

    names = set()

    def walk(patterns, ns=None):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns, pattern.namespace or ns)
            elif pattern.name:
                names.add(f"{ns}:{pattern.name}" if ns else pattern.name)

    walk(book_urlpatterns)
    return names


def contents(response) -> str:
    """The response as text; a zip download is searched member by member."""
    body = getattr(response, "content", b"")
    if response.get("Content-Type", "").startswith("application/zip"):
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            return "\n".join(archive.read(name).decode("utf-8", "replace") for name in archive.namelist())
    if hasattr(response, "streaming_content"):
        return b"".join(response.streaming_content).decode("utf-8", "replace")
    return body.decode("utf-8", "replace")


class TwoBooksTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Isolation Team", slug="isolation")
        cls.user = CustomUser.objects.create_user(username="iso@example.com", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.a = build_book_data(cls.team.default_book, MARK_A, cls.user)
        cls.b = build_book_data(second_book(cls.team), MARK_B, cls.user)

    def setUp(self):
        self.client.force_login(self.user)

    def url(self, name, **kwargs):
        return reverse(name, kwargs={"team_slug": self.team.slug, "book_slug": self.a.book.slug, **kwargs})


class CoverageTest(TestCase):
    def test_every_book_url_is_covered(self):
        tables = [set(READS), set(QUERY_OBJECTS), set(OBJECTS), set(WRITES), set(EXEMPT)]
        covered = set().union(*tables)
        self.assertEqual(
            book_url_names() - covered,
            set(),
            "New book URL(s) with no isolation coverage: add each to READS, OBJECTS, WRITES or EXEMPT.",
        )
        self.assertEqual(covered - book_url_names(), set(), "Coverage entries for URL names that no longer exist.")

    def test_no_url_is_in_two_tables(self):
        # journal-entry-list and reconciliation-list are read *and* written, on purpose.
        pairs = [(READS, OBJECTS), (READS, QUERY_OBJECTS), (OBJECTS, WRITES), (WRITES, EXEMPT), (READS, EXEMPT)]
        for left, right in pairs:
            self.assertEqual((set(left) & set(right)) - WRITE_OVERRIDES, set())


class ReadIsolationTest(TwoBooksTestCase):
    def test_book_a_pages_show_none_of_book_b(self):
        for name, query in READS.items():
            params = query(self.a, self.b) if callable(query) else query
            with self.subTest(name=name):
                response = self.client.get(self.url(name), params)
                self.assertLess(response.status_code, 500, name)
                self.assertNotIn(MARK_B, contents(response), f"{name} leaked book B")

    def test_the_pages_do_show_book_a(self):
        """Guards the test itself: a page that renders nothing would pass the check above."""
        for name in (
            "accounts:accounts_home",
            "journal:transaction-list",
            "bank_feed:bank-feed-list",
            "budget:goals_list",
            "reports:income_statement",
            "reports:export_transactions",
            "portability:export",
        ):
            query = READS[name]
            params = {"account": self.a.chequing.id} if callable(query) else query
            with self.subTest(name=name):
                self.assertIn(MARK_A, contents(self.client.get(self.url(name), params)))

    def test_import_status_of_book_b_is_a_404(self):
        for name, query in QUERY_OBJECTS.items():
            with self.subTest(name=name):
                self.assertEqual(self.client.get(self.url(name), query(self.b)).status_code, 404)


class ObjectIsolationTest(TwoBooksTestCase):
    def test_book_b_objects_are_404_under_book_a(self):
        before = snapshot(self.b.book)
        for name, (kind, kwarg, method) in OBJECTS.items():
            obj = self.b.object_for(kind)
            with self.subTest(name=name):
                url = self.url(name, **{kwarg: obj.pk})
                if method == "get":
                    response = self.client.get(url)
                else:
                    response = getattr(self.client, method)(url, data="{}", content_type="application/json")
                self.assertEqual(response.status_code, 404, name)
        self.assertEqual(snapshot(self.b.book), before)

    def test_the_same_objects_open_under_their_own_book(self):
        """The 404s above are about the book, not a broken URL."""
        for name in ("accounts:account_detail", "journal:journal-entry-detail", "budget:goal_detail"):
            kind, kwarg, _method = OBJECTS[name]
            url = reverse(
                name,
                kwargs={"team_slug": self.team.slug, "book_slug": self.b.book.slug, kwarg: self.b.object_for(kind).pk},
            )
            with self.subTest(name=name):
                self.assertEqual(self.client.get(url).status_code, 200)


class WriteIsolationTest(TwoBooksTestCase):
    def test_writes_under_book_a_leave_book_b_untouched(self):
        for name, body in WRITES.items():
            if name in WRITE_OVERRIDES:
                continue
            before = snapshot(self.b.book)
            with self.subTest(name=name):
                response = self.client.post(
                    self.url(name), data=json.dumps(body(self.a, self.b)), content_type="application/json"
                )
                self.assertLess(response.status_code, 500, name)
                self.assertEqual(snapshot(self.b.book), before, f"{name} changed book B")

    def test_a_journal_entry_cannot_post_to_book_b_accounts(self):
        before = snapshot(self.b.book)
        response = self.client.post(
            self.url("journal:journal-entry-list"),
            data=json.dumps(
                {
                    "entry_date": "2026-03-10",
                    "description": "cross-book",
                    "lines": [
                        {"account": self.b.groceries.id, "dr_amount": "5.00", "cr_amount": "0"},
                        {"account": self.a.chequing.id, "dr_amount": "0", "cr_amount": "5.00"},
                    ],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(snapshot(self.b.book), before)

    def test_a_statement_cannot_be_started_on_a_book_b_account(self):
        before = snapshot(self.b.book)
        response = self.client.post(
            self.url("reconciliation:reconciliation-list"),
            data=json.dumps({"account": self.b.chequing.id, "statement_date": "2026-03-31", "statement_balance": "0"}),
            content_type="application/json",
        )
        self.assertIn(response.status_code, (400, 404))
        self.assertEqual(snapshot(self.b.book), before)

    def test_recategorizing_a_book_a_line_into_book_b_is_refused(self):
        before = snapshot(self.b.book)
        line = self.a.entry.lines.get(account=self.a.groceries)
        response = self.client.post(
            self.url("journal:line-recategorize", pk=line.pk),
            data=json.dumps({"new_category_id": self.b.groceries.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(snapshot(self.b.book), before)


class BudgetCoverIsolationTest(TwoBooksTestCase):
    def test_a_book_b_category_cannot_be_covered(self):
        before = snapshot(self.b.book)
        response = self.client.post(
            self.url("budget:budget_cover"),
            data=json.dumps({"category_id": self.b.groceries.id, "month": "2026-03-01", "amount": "10"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(snapshot(self.b.book), before)


class BudgetFallbackTest(TwoBooksTestCase):
    """The no-JS budget form post names rows by id; B's ids are 404s."""

    def test_budget_id_of_book_b_is_a_404(self):
        response = self.client.post(
            self.url("budget:budget_home") + "?month=2026-03-01",
            {"budget_id": self.b.budget.id, "budget_amount": "1"},
        )
        self.assertEqual(response.status_code, 404)
        self.b.budget.refresh_from_db()
        self.assertEqual(str(self.b.budget.budget_amount), "300.00")

    def test_autofill_ignores_book_b_categories(self):
        before = snapshot(self.b.book)
        self.client.post(
            self.url("budget:budget_autofill"),
            {"action": "zero", "month": "2026-03-01", "filtered": "1", "category_ids": [self.b.groceries.id]},
        )
        self.assertEqual(snapshot(self.b.book), before)


class CrossTeamTest(TestCase):
    """A member of team X gets a 404 for every book of team Y, as before books existed."""

    @classmethod
    def setUpTestData(cls):
        cls.mine = Team.objects.create(name="Mine", slug="mine")
        cls.theirs = Team.objects.create(name="Theirs", slug="theirs")
        cls.user = CustomUser.objects.create_user(username="x@example.com", password="pass")
        cls.mine.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.their_data = build_book_data(cls.theirs.default_book, MARK_B)
        # A slug only team Theirs has -- both teams have a `personal` book.
        cls.their_business = second_book(cls.theirs)

    def setUp(self):
        self.client.force_login(self.user)

    def test_every_read_of_another_teams_book_is_a_404(self):
        for name, query in READS.items():
            if name.endswith(":api-root"):
                # DRF's router root lists endpoint URLs, never data, and has no
                # object permissions of its own -- as it did before books.
                continue
            params = query(self.their_data, self.their_data) if callable(query) else query
            with self.subTest(name=name):
                response = self.client.get(reverse(name, args=self.their_data.book.url_args), params)
                self.assertIn(response.status_code, (403, 404), name)

    def test_another_teams_book_under_my_team_slug_is_a_404(self):
        """The book is looked up inside the URL's team, even for someone who belongs to both."""
        self.theirs.members.add(self.user, through_defaults={"role": ROLE_ADMIN})
        response = self.client.get(reverse("web_book:home", args=[self.mine.slug, self.their_business.slug]))
        self.assertEqual(response.status_code, 404)
