from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Account, AccountGroup
from apps.audit.models import AuditEvent
from apps.books.helpers import create_book, reserved_book_slugs, unique_book_slug, url_segments
from apps.books.models import DEFAULT_BOOK_NAME, DEFAULT_BOOK_SLUG, Book
from apps.budget.models import Budget
from apps.budget.unassigned import compute_unassigned
from apps.journal.models import JournalEntry, JournalLine
from apps.onboarding.models import OnboardingState
from apps.reports.services import ReportService
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

from .factories import build_book_data, snapshot


def make_team(slug="books-team", role=ROLE_ADMIN):
    team = Team.objects.create(name=slug.title(), slug=slug)
    user = CustomUser.objects.create_user(username=f"{slug}@example.com", password="pass")
    team.members.add(user, through_defaults={"role": role})
    return team, user


def finish_onboarding(book):
    state, _ = OnboardingState.objects.get_or_create(book=book)
    state.complete()
    state.finish_tasks()
    state.save()


class BookModelTest(TestCase):
    def test_a_new_team_gets_a_personal_book(self):
        team = Team.objects.create(name="Fresh", slug="fresh")
        books = list(team.books.all())
        self.assertEqual(len(books), 1)
        self.assertEqual((books[0].name, books[0].slug), (DEFAULT_BOOK_NAME, DEFAULT_BOOK_SLUG))
        # New books start with the future-income setting off (D5).
        self.assertFalse(books[0].budget_future_income)

    def test_slug_is_derived_from_the_name_and_unique_within_the_team(self):
        team = Team.objects.create(name="Slugs", slug="slugs")
        self.assertEqual(create_book(team, "Rental Property").slug, "rental-property")
        self.assertEqual(create_book(team, "Rental property!").slug, "rental-property-2")
        # Another team may reuse it.
        other = Team.objects.create(name="Other", slug="other-slugs")
        self.assertEqual(create_book(other, "Rental Property").slug, "rental-property")

    def test_a_reserved_slug_is_suffixed(self):
        team = Team.objects.create(name="Reserved", slug="reserved")
        for name in ("Budget", "Settings", "Team", "Reports"):
            with self.subTest(name=name):
                slug = unique_book_slug(team, name)
                self.assertNotIn(slug, reserved_book_slugs())
                self.assertTrue(slug.startswith(name.lower()))

    def test_renaming_keeps_the_slug(self):
        team = Team.objects.create(name="Rename", slug="rename")
        book = create_book(team, "Business")
        book.name = "Consulting"
        book.save()
        book.refresh_from_db()
        self.assertEqual(book.slug, "business")

    def test_new_books_sort_after_existing_ones(self):
        team = Team.objects.create(name="Order", slug="order")
        second = create_book(team, "Aardvark")
        self.assertGreater(second.sort_order, team.default_book.sort_order)
        # The default book stays the first one, not the alphabetically first.
        self.assertEqual(team.default_book.slug, DEFAULT_BOOK_SLUG)

    def test_url_args(self):
        team = Team.objects.create(name="Args", slug="args")
        book = team.default_book
        self.assertEqual(book.url_args, ("args", "personal"))
        self.assertEqual(book.base_url, "/a/args/personal/")
        self.assertEqual(book.get_absolute_url(), "/a/args/personal/")


class ReservedSlugsTest(TestCase):
    """The reserved list is read off the URLconf, so it cannot fall behind it."""

    def test_every_first_segment_of_both_url_levels_is_reserved(self):
        from koala_budget.urls import book_urlpatterns, team_level_urlpatterns

        segments = url_segments(team_level_urlpatterns) | url_segments(book_urlpatterns)
        self.assertLessEqual(segments, reserved_book_slugs())
        # Spot-check the ones the plan names, on both levels.
        for slug in ("team", "subscription", "settings", "books", "budget", "bankfeed", "ynab-import", "data"):
            self.assertIn(slug, reserved_book_slugs())


class RequestPlumbingTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user = make_team("plumbing")
        cls.personal = cls.team.default_book
        cls.business = create_book(cls.team, "Business")
        finish_onboarding(cls.personal)
        finish_onboarding(cls.business)

    def setUp(self):
        self.client.force_login(self.user)

    def test_request_book_is_the_urls_book(self):
        response = self.client.get(reverse("web_book:home", args=self.business.url_args))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.wsgi_request.book, self.business)
        self.assertEqual(response.context["nav_book"], self.business)

    def test_an_unknown_book_slug_is_a_404(self):
        self.assertEqual(self.client.get("/a/plumbing/nope/budget/").status_code, 404)

    def test_team_root_opens_the_last_book_used(self):
        self.client.get(reverse("budget:budget_home", args=self.business.url_args))
        response = self.client.get(reverse("web_team:home", args=[self.team.slug]))
        self.assertRedirects(response, reverse("web_book:home", args=self.business.url_args))

    def test_team_root_defaults_to_the_default_book(self):
        response = self.client.get(reverse("web_team:home", args=[self.team.slug]))
        self.assertRedirects(response, reverse("web_book:home", args=self.personal.url_args))

    def test_team_level_pages_keep_their_urls_and_follow_the_nav_book(self):
        self.client.get(reverse("web_book:home", args=self.business.url_args))
        response = self.client.get(reverse("single_team:manage_team", args=[self.team.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.book)
        # The sidebar still points at the book last opened.
        self.assertContains(response, reverse("budget:budget_home", args=self.business.url_args))

    def test_the_switcher_lists_the_teams_books(self):
        response = self.client.get(reverse("web_book:home", args=self.personal.url_args))
        self.assertContains(response, 'data-testid="book-switch-personal"')
        self.assertContains(response, 'data-testid="book-switch-business"')
        self.assertContains(response, reverse("books_team:create", args=[self.team.slug]))

    def test_a_single_book_team_sees_no_book_name_on_the_dashboard(self):
        team, user = make_team("single-book")
        finish_onboarding(team.default_book)
        self.client.force_login(user)
        response = self.client.get(reverse("web_book:home", args=team.default_book.url_args))
        self.assertNotContains(response, 'data-testid="dashboard-book-name"')
        self.assertEqual(response.context["page_title"], "Single-Book Home")

    def test_a_multi_book_team_names_the_book(self):
        response = self.client.get(reverse("web_book:home", args=self.business.url_args))
        self.assertContains(response, 'data-testid="dashboard-book-name"')
        self.assertEqual(response.context["page_title"], "Plumbing · Business Home")


class LegacyRedirectTest(TestCase):
    """Pre-books links (`/a/{team}/budget/...`) 301 to the team's default book."""

    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user = make_team("legacy")
        cls.book = cls.team.default_book
        create_book(cls.team, "Business")  # the default book stays the first one

    def setUp(self):
        self.client.force_login(self.user)

    def test_every_book_level_prefix_redirects(self):
        from koala_budget.urls import book_urlpatterns, team_level_urlpatterns

        for prefix in sorted(url_segments(book_urlpatterns) - url_segments(team_level_urlpatterns)):
            with self.subTest(prefix=prefix):
                response = self.client.get(f"/a/legacy/{prefix}/some/path/?month=2026-03-01&x=1")
                self.assertEqual(response.status_code, 301)
                self.assertEqual(response["Location"], f"/a/legacy/personal/{prefix}/some/path/?month=2026-03-01&x=1")

    def test_a_legacy_link_lands_on_a_working_page(self):
        response = self.client.get("/a/legacy/budget/", follow=True)
        self.assertEqual(response.redirect_chain[0], ("/a/legacy/personal/budget/", 301))

    def test_a_post_to_an_old_url_is_a_404(self):
        self.assertEqual(self.client.post("/a/legacy/budget/save-amount/", {}).status_code, 404)

    def test_an_anonymous_user_is_sent_to_log_in(self):
        self.client.logout()
        response = self.client.get("/a/legacy/budget/")
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("account_login"), response["Location"])

    def test_a_non_member_gets_a_404(self):
        _team, outsider = make_team("outsider-legacy")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get("/a/legacy/budget/").status_code, 404)

    def test_team_level_pages_are_not_redirected(self):
        self.assertEqual(self.client.get(reverse("web_team:settings", args=[self.team.slug])).status_code, 200)
        self.assertEqual(self.client.get(reverse("single_team:manage_team", args=[self.team.slug])).status_code, 200)


class BookCreateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team, cls.admin = make_team("create")
        cls.member = CustomUser.objects.create_user(username="member-create@example.com", password="pass")
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})

    def create(self, name, start="questionnaire"):
        return self.client.post(reverse("books_team:create", args=[self.team.slug]), {"name": name, "start": start})

    def test_admin_creates_a_book_that_starts_in_onboarding(self):
        self.client.force_login(self.admin)
        response = self.create("Side Business")
        book = Book.objects.get(team=self.team, name="Side Business")
        self.assertRedirects(response, reverse("onboarding:home", args=book.url_args), fetch_redirect_response=False)
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.BOOK_CREATED, book=book).exists())
        # Nothing of the other book came with it.
        self.assertFalse(Account.objects.filter(book=book).exists())

    def test_the_book_home_sends_a_new_book_into_the_walkthrough(self):
        self.client.force_login(self.admin)
        self.create("Rental")
        book = Book.objects.get(team=self.team, name="Rental")
        response = self.client.get(reverse("web_book:home", args=book.url_args))
        self.assertRedirects(response, reverse("onboarding:home", args=book.url_args), fetch_redirect_response=False)

    def test_the_other_starts(self):
        self.client.force_login(self.admin)
        response = self.create("From YNAB", start="ynab")
        book = Book.objects.get(team=self.team, name="From YNAB")
        self.assertRedirects(response, reverse("ynab_import:home", args=book.url_args), fetch_redirect_response=False)
        response = self.create("From Export", start="export")
        book = Book.objects.get(team=self.team, name="From Export")
        self.assertRedirects(response, reverse("portability:home", args=book.url_args), fetch_redirect_response=False)

    def test_a_duplicate_name_is_refused(self):
        self.client.force_login(self.admin)
        response = self.create("personal")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.team.books.count(), 1)

    def test_a_member_cannot_create_a_book(self):
        self.client.force_login(self.member)
        self.assertEqual(self.create("Nope").status_code, 404)
        self.assertEqual(self.team.books.count(), 1)


class BookSettingsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team, cls.admin = make_team("settings-team")
        cls.book = create_book(cls.team, "Business")

    def setUp(self):
        self.client.force_login(self.admin)

    def post(self, **data):
        return self.client.post(reverse("books:settings", args=self.book.url_args), data)

    def test_rename_and_change_the_address(self):
        response = self.post(name="Consulting", slug="consulting")
        self.book.refresh_from_db()
        self.assertEqual((self.book.name, self.book.slug), ("Consulting", "consulting"))
        self.assertRedirects(response, reverse("books:settings", args=self.book.url_args))

    def test_a_reserved_address_is_refused(self):
        response = self.post(name="Business", slug="budget")
        self.assertEqual(response.status_code, 200)
        self.book.refresh_from_db()
        self.assertEqual(self.book.slug, "business")

    def test_another_books_address_is_refused(self):
        self.post(name="Business", slug="personal")
        self.book.refresh_from_db()
        self.assertEqual(self.book.slug, "business")

    def test_a_member_cannot_change_settings(self):
        member = CustomUser.objects.create_user(username="m-settings@example.com", password="pass")
        self.team.members.add(member, through_defaults={"role": ROLE_MEMBER})
        self.client.force_login(member)
        self.assertEqual(self.post(name="Hijacked", slug="business").status_code, 404)


class BookArchiveTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team, cls.admin = make_team("archive-team")
        cls.personal = cls.team.default_book
        cls.business = create_book(cls.team, "Business")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_archive_and_restore(self):
        response = self.client.post(reverse("books:archive", args=self.business.url_args), {"confirm": "Business"})
        self.assertRedirects(response, reverse("books_team:list", args=[self.team.slug]))
        self.business.refresh_from_db()
        self.assertTrue(self.business.is_archived)
        # Out of the switcher; still restorable.
        page = self.client.get(reverse("budget:budget_home", args=self.personal.url_args))
        self.assertNotContains(page, 'data-testid="book-switch-business"')
        self.client.post(reverse("books:restore", args=self.business.url_args))
        self.business.refresh_from_db()
        self.assertFalse(self.business.is_archived)

    def test_the_name_must_be_typed(self):
        self.client.post(reverse("books:archive", args=self.business.url_args), {"confirm": "wrong"})
        self.business.refresh_from_db()
        self.assertFalse(self.business.is_archived)

    def test_the_last_open_book_cannot_be_archived(self):
        self.client.post(reverse("books:archive", args=self.business.url_args), {"confirm": "Business"})
        self.client.post(reverse("books:archive", args=self.personal.url_args), {"confirm": "Personal"})
        self.personal.refresh_from_db()
        self.assertFalse(self.personal.is_archived)


class BookDeleteTest(TestCase):
    """Deleting a book removes its rows and nothing else -- with another book populated beside it."""

    @classmethod
    def setUpTestData(cls):
        cls.team, cls.admin = make_team("delete-team")
        cls.keep = build_book_data(cls.team.default_book, "KEEPME", cls.admin)
        cls.gone = build_book_data(create_book(cls.team, "Business"), "GONE", cls.admin)

    def setUp(self):
        self.client.force_login(self.admin)

    def delete(self, book, confirm):
        return self.client.post(reverse("books:delete", args=book.url_args), {"delete-confirm": confirm})

    def test_delete_wipes_only_that_book(self):
        before = snapshot(self.keep.book)
        response = self.delete(self.gone.book, "Business")
        self.assertRedirects(response, reverse("web_team:home", args=[self.team.slug]), fetch_redirect_response=False)
        self.assertFalse(Book.objects.filter(pk=self.gone.book.pk).exists())
        self.assertFalse(JournalEntry.objects.filter(description__contains="GONE").exists())
        self.assertEqual(snapshot(self.keep.book), before)
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.BOOK_DELETED, team=self.team).exists())

    def test_the_name_must_be_typed(self):
        self.delete(self.gone.book, "business")
        self.assertTrue(Book.objects.filter(pk=self.gone.book.pk).exists())

    def test_the_last_book_cannot_be_deleted(self):
        self.delete(self.gone.book, "Business")
        self.delete(self.keep.book, "Personal")
        self.assertTrue(Book.objects.filter(pk=self.keep.book.pk).exists())


class WipeBookTest(TestCase):
    """`wipe_book` (the export/import wipe) touches one book only."""

    def test_wipe_leaves_the_sibling_book(self):
        from apps.portability.services.wipe import wipe_book

        team, admin = make_team("wipe-team")
        keep = build_book_data(team.default_book, "KEEPER", admin)
        gone = build_book_data(create_book(team, "Other"), "WIPED", admin)
        before = snapshot(keep.book)
        wipe_book(gone.book)
        self.assertEqual(snapshot(keep.book), before)
        self.assertFalse(Account.objects.filter(book=gone.book).exists())
        self.assertFalse(JournalLine.objects.filter(book=gone.book).exists())


class FutureIncomeTest(TestCase):
    """`Book.budget_future_income` (docs/books-plan.md §6)."""

    MONTH = date.today().replace(day=1)

    @classmethod
    def setUpTestData(cls):
        cls.team, cls.admin = make_team("future-income")
        cls.book = cls.team.default_book
        finish_onboarding(cls.book)
        income = AccountGroup.objects.create(book=cls.book, name="Work", account_type="income")
        expense = AccountGroup.objects.create(book=cls.book, name="Living", account_type="expense")
        cls.salary = Account.objects.create(book=cls.book, name="Salary", account_group=income)
        cls.rent = Account.objects.create(book=cls.book, name="Rent", account_group=expense)
        Budget.objects.create(book=cls.book, month=cls.MONTH, category=cls.salary, budget_amount=Decimal("5000"))
        Budget.objects.create(book=cls.book, month=cls.MONTH, category=cls.rent, budget_amount=Decimal("1500"))

    def setUp(self):
        self.client.force_login(self.admin)

    def set_future_income(self, value):
        self.book.budget_future_income = value
        self.book.save()

    def test_off_counts_income_only_once_it_lands(self):
        self.set_future_income(False)
        self.assertEqual(compute_unassigned(self.book, self.MONTH).income_due, Decimal("0"))
        self.set_future_income(True)
        self.assertEqual(compute_unassigned(self.book, self.MONTH).income_due, Decimal("5000"))

    def test_the_budget_page_hides_income_while_off_and_restores_it(self):
        url = reverse("budget:budget_home", args=self.book.url_args)
        self.set_future_income(False)
        keys = [s["key"] for s in self.client.get(url).context["sections"] if s["groups"]]
        self.assertEqual(keys, ["expense"])
        # The rows are kept, so switching back restores them.
        self.assertTrue(Budget.objects.filter(book=self.book, category=self.salary).exists())
        self.set_future_income(True)
        keys = [s["key"] for s in self.client.get(url).context["sections"] if s["groups"]]
        self.assertEqual(keys, ["income", "expense"])

    def test_saving_an_income_budget_is_refused_while_off(self):
        self.set_future_income(False)
        response = self.client.post(
            reverse("budget:budget_save_amount", args=self.book.url_args),
            data={"category_id": self.salary.id, "month": self.MONTH.isoformat(), "amount": "1"},
            content_type="application/json",
        )
        self.assertGreaterEqual(response.status_code, 400)
        response = self.client.post(
            reverse("budget:budget_grid_save", args=self.book.url_args),
            data={"changes": [{"category_id": self.salary.id, "month": self.MONTH.isoformat(), "amount": "1"}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Budget.objects.get(book=self.book, category=self.salary).budget_amount, Decimal("5000"))

    def test_budget_vs_actual_hides_income_while_off(self):
        self.set_future_income(False)
        response = self.client.get(reverse("reports:budget_vs_actual", args=self.book.url_args))
        self.assertEqual(response.context["income_groups"], [])
        chart = ReportService(self.book).get_budget_vs_actual_chart_data(self.salary, self.MONTH, self.MONTH)
        self.assertIsNone(chart)

    def test_the_settings_page_states_the_consequence(self):
        self.set_future_income(True)
        response = self.client.get(reverse("books:budgeting", args=self.book.url_args))
        self.assertEqual(response.context["unassigned_now"].income_due, Decimal("5000"))
        self.assertEqual(response.context["unassigned_flipped"].income_due, Decimal("0"))
        self.assertEqual(
            response.context["unassigned_now"].amount - response.context["unassigned_flipped"].amount, Decimal("5000")
        )

    def test_the_settings_page_saves_and_records_the_change(self):
        self.set_future_income(True)
        self.client.post(reverse("books:budgeting", args=self.book.url_args), {})
        self.book.refresh_from_db()
        self.assertFalse(self.book.budget_future_income)
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.BOOK_SETTINGS_CHANGED, book=self.book).exists())

    @override_settings(ONBOARDING_ENABLED=True)
    def test_onboarding_answer_sets_the_book(self):
        from apps.onboarding.questions import book_settings

        self.assertEqual(book_settings({"budget_future_income": "yes"}), {"budget_future_income": True})
        self.assertEqual(book_settings({"budget_future_income": "no"}), {"budget_future_income": False})
        self.assertEqual(book_settings({"budget_future_income": "a removed option"}), {})
