"""
The Settings hub and the section list behind it.

What matters here is not the hub's markup but the promise the rail makes: every
page it links to must exist and must render inside the settings shell, and a
section a user may not use must not be offered. Those are the two ways a
consolidation like this rots -- a link that 404s, or one that shows someone a
page they will be refused.
"""

from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser
from apps.web.settings_sections import sections_for


class SettingsHubTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.admin = CustomUser.objects.create_user(username="admin@example.com", password="testpass123")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.member = CustomUser.objects.create_user(username="member@example.com", password="testpass123")
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})
        cls.outsider = CustomUser.objects.create_user(username="outsider@example.com", password="testpass123")
        cls.url = reverse("web_team:settings", kwargs={"team_slug": cls.team.slug})

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_non_member_is_refused(self):
        self.client.force_login(self.outsider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_renders_for_a_member(self):
        self.client.force_login(self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="settings-hub"')
        self.assertContains(response, 'data-testid="settings-nav"')

    def test_hub_links_to_every_section_it_offers(self):
        """A card for a section the user cannot reach is worse than no card."""
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        for section in sections_for(response.wsgi_request):
            with self.subTest(section=section.key):
                self.assertContains(response, f'href="{section.url}"')
                if section.key == "subscription":
                    # Subscription answers 500 with a "check your Stripe setup"
                    # page when no products are configured, which is the case in
                    # tests. That it renders at all is covered by the
                    # subscriptions app's own suite.
                    continue
                self.assertEqual(self.client.get(section.url).status_code, 200)

    def test_sidebar_offers_settings(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertContains(response, 'data-testid="nav-settings"')

    def test_moved_pages_left_the_sidebars_manage_group(self):
        """
        Asserted against the nav include itself rather than the whole page:
        the hub and rail link to all three, so counting occurrences on the page
        would measure the wrong thing.
        """
        self.client.force_login(self.admin)
        request = self.client.get(self.url).wsgi_request
        nav = render_to_string("web/components/app_nav_menu_items.html", request=request)
        for url_name in ("single_team:manage_team", "audit:audit_log", "subscriptions_team:subscription_details"):
            with self.subTest(url_name=url_name):
                self.assertNotIn(reverse(url_name, args=[self.team.slug]), nav)
        self.assertIn(reverse("accounts:accounts_home", args=[self.team.slug]), nav)


class TeamSwitcherRemovedTest(TestCase):
    """The sidebar's team card is gone; Team settings and Add a team live in Settings."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="admin@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

    def test_sidebar_has_no_team_switcher(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("web_team:settings", kwargs={"team_slug": self.team.slug}))
        self.assertNotContains(response, 'data-testid="team-switcher"')

    def test_settings_offers_add_a_team(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("web_team:settings", kwargs={"team_slug": self.team.slug}))
        self.assertContains(response, 'data-testid="settings-card-add_team"')
        self.assertContains(response, f'href="{reverse("teams:manage_teams")}new"')


class SettingsSectionsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.admin = CustomUser.objects.create_user(username="admin@example.com", password="testpass123")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.member = CustomUser.objects.create_user(username="member@example.com", password="testpass123")
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})

    def _sections(self, user):
        self.client.force_login(user)
        response = self.client.get(reverse("web_team:settings", kwargs={"team_slug": self.team.slug}))
        return {s.key for s in sections_for(response.wsgi_request)}

    def test_admin_sees_every_section(self):
        self.assertEqual(
            self._sections(self.admin),
            {"profile", "password", "team", "subscription", "add_team", "import", "data_transfer", "audit"},
        )

    def test_member_is_not_offered_subscription(self):
        """Billing is admin-only, and the view refuses a member — so don't offer it."""
        self.assertNotIn("subscription", self._sections(self.member))

    def test_password_section_is_skipped_without_a_usable_password(self):
        """A social-only account has no password to change."""
        self.admin.set_unusable_password()
        self.admin.save()
        self.assertNotIn("password", self._sections(self.admin))


class SettingsShellOnAccountPagesTest(TestCase):
    """
    Profile and Change Password live on non-team URLs, where `request.team` is
    None. The rail has to fall back to the user's default team, or those two
    pages lose every team-scoped section from it.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="user@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

    def setUp(self):
        self.client.force_login(self.user)

    def test_profile_renders_the_full_settings_rail(self):
        response = self.client.get(reverse("users:user_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="settings-nav-team"')
        self.assertContains(response, 'data-testid="settings-nav-audit"')

    def test_change_password_renders_the_full_settings_rail(self):
        response = self.client.get(reverse("account_change_password"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="settings-nav-password"')
        self.assertContains(response, 'data-testid="settings-nav-import"')

    def test_account_pages_keep_the_main_sidebar(self):
        """
        The sidebar is chrome, and it used to vanish entirely on Profile and
        Change Password because `request.team` is None there. Those are the
        first two pages the user menu links to, so the nav has to survive them.
        """
        for url in (reverse("users:user_profile"), reverse("account_change_password")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, reverse("web_team:home", args=[self.team.slug]))
                self.assertContains(response, reverse("budget:budget_home", args=[self.team.slug]))
                self.assertContains(response, reverse("accounts:accounts_home", args=[self.team.slug]))

    def test_a_team_page_follows_its_own_team_not_the_default(self):
        """
        The nav's team falls back to the default only when the URL has none.
        A page that names a team must never be framed by another team's nav —
        that is how someone ends up acting on the wrong books.
        """
        other = Team.objects.create(name="Other Team", slug="other-team")
        other.members.add(self.user, through_defaults={"role": ROLE_ADMIN})
        response = self.client.get(reverse("web_team:settings", kwargs={"team_slug": other.slug}))
        self.assertContains(response, reverse("budget:budget_home", args=[other.slug]))
        self.assertNotContains(response, reverse("budget:budget_home", args=[self.team.slug]))

    def test_an_account_page_follows_the_team_last_worked_in(self):
        self.client.get(reverse("web_team:home", kwargs={"team_slug": self.team.slug}))
        response = self.client.get(reverse("users:user_profile"))
        self.assertContains(response, reverse("budget:budget_home", args=[self.team.slug]))

    def test_a_user_with_no_team_still_gets_the_account_sections(self):
        loner = CustomUser.objects.create_user(username="loner@example.com", password="testpass123")
        self.client.force_login(loner)
        response = self.client.get(reverse("users:user_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="settings-nav-profile"')
        self.assertNotContains(response, 'data-testid="settings-nav-team"')
