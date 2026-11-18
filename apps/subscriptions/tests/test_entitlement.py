"""
Subscription gating (`apps.subscriptions.entitlement`): the free trial, founding
spots, the read-only gate on book writes, the background jobs it pauses, and
checkout's per-team prices.
"""

from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from djstripe.enums import SubscriptionStatus
from rest_framework.test import APIClient

from apps.accounts.models import Payee
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services import recurring
from apps.bank_feed.tests.test_recurring import RecurringFixture
from apps.plaid import tasks as plaid_tasks
from apps.plaid.tests.base import PlaidBookTestCase
from apps.subscriptions import entitlement
from apps.subscriptions.exceptions import PriceNotAllowedError, SubscriptionConfigError
from apps.subscriptions.helpers import _trial_kwargs, create_stripe_checkout_session
from apps.subscriptions.metadata import ACTIVE_PRODUCTS, ProductMetadata, allowed_price_ids, products_for_team
from apps.subscriptions.tests.utils import create_stripe_product, create_subscription_for_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

STANDARD = next(p for p in ACTIVE_PRODUCTS if p.is_default)
FOUNDING_ID = "prod_founding_test"


def expire_trial(team):
    team.trial_ends_at = timezone.now() - timedelta(days=1)
    team.save(update_fields=["trial_ends_at"])


class TrialAndFoundingTest(TestCase):
    def test_a_new_team_gets_the_trial(self):
        team = Team.objects.create(name="New", slug="new")
        expected = timezone.now() + timedelta(days=60)
        self.assertLess(abs(team.trial_ends_at - expected), timedelta(minutes=1))
        self.assertEqual(entitlement.team_access(team).status, entitlement.TRIAL)

    def test_the_first_teams_are_founding_members_until_the_limit(self):
        with override_settings(FOUNDING_MEMBER_LIMIT=2):
            first = Team.objects.create(name="One", slug="one")
            second = Team.objects.create(name="Two", slug="two")
            third = Team.objects.create(name="Three", slug="three")
        self.assertEqual([first.is_founding_member, second.is_founding_member, third.is_founding_member], [1, 1, 0])

    def test_saving_an_existing_team_never_changes_its_spot(self):
        with override_settings(FOUNDING_MEMBER_LIMIT=0):
            team = Team.objects.create(name="Late", slug="late")
        with override_settings(FOUNDING_MEMBER_LIMIT=500):
            team.name = "Renamed"
            team.save()
        team.refresh_from_db()
        self.assertFalse(team.is_founding_member)


class AccessStateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="T", slug="t")

    def status(self):
        team = Team.objects.get(pk=self.team.pk)
        state = entitlement.team_access(team).status
        # The queryset filter the background jobs use must agree with the per-team check.
        in_q = Team.objects.filter(entitlement.entitled_teams_q(), pk=team.pk).exists()
        self.assertEqual(in_q, state != entitlement.READ_ONLY)
        return state

    def test_trial(self):
        self.assertEqual(self.status(), entitlement.TRIAL)

    def test_an_ended_trial_is_read_only(self):
        expire_trial(self.team)
        self.assertEqual(self.status(), entitlement.READ_ONLY)

    def test_complimentary_is_never_read_only(self):
        expire_trial(self.team)
        Team.objects.filter(pk=self.team.pk).update(is_complimentary=True)
        self.assertEqual(self.status(), entitlement.COMPLIMENTARY)

    def test_a_subscription_outlasts_the_trial(self):
        expire_trial(self.team)
        create_subscription_for_team(self.team, STANDARD)
        self.assertEqual(self.status(), entitlement.SUBSCRIBED)

    def test_a_canceled_subscription_after_the_trial_is_read_only(self):
        expire_trial(self.team)
        subscription = create_subscription_for_team(self.team, STANDARD)
        subscription.status = SubscriptionStatus.canceled
        subscription.save()
        self.assertEqual(self.status(), entitlement.READ_ONLY)

    def test_the_banner_shows_only_in_the_last_two_weeks_and_when_read_only(self):
        self.team.trial_ends_at = timezone.now() + timedelta(days=30)
        self.assertFalse(entitlement.team_access(self.team).show_banner)
        self.team.trial_ends_at = timezone.now() + timedelta(days=10)
        self.assertTrue(entitlement.team_access(self.team).show_banner)
        self.assertEqual(entitlement.team_access(self.team).trial_days_left, 10)
        expire_trial(self.team)
        self.assertTrue(entitlement.team_access(self.team).show_banner)


class ReadOnlyGateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Gate", slug="gate")
        cls.book = cls.team.default_book
        cls.admin = CustomUser.objects.create_user(username="gate-admin", password="pass")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.member = CustomUser.objects.create_user(username="gate-member", password="pass")
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})
        cls.outsider = CustomUser.objects.create_user(username="gate-outsider", password="pass")

    def setUp(self):
        self.client.force_login(self.admin)
        self.payee_create = reverse("accounts:payee_create", args=self.book.url_args)

    def test_a_trial_team_writes(self):
        response = self.client.post(self.payee_create, {"name": "Grocer"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Payee.objects.filter(book=self.book, name="Grocer").exists())

    def test_a_form_post_is_refused_with_a_message_and_writes_nothing(self):
        expire_trial(self.team)
        referer = "http://testserver" + reverse("accounts:payee_list", args=self.book.url_args)
        response = self.client.post(self.payee_create, {"name": "Grocer"}, HTTP_REFERER=referer, follow=True)
        self.assertEqual(response.redirect_chain[0], (referer, 302))
        self.assertContains(response, "read-only")
        self.assertFalse(Payee.objects.filter(book=self.book).exists())

    def test_a_json_write_gets_a_402(self):
        expire_trial(self.team)
        url = reverse("accounts:api_create_group", args=self.book.url_args)
        response = self.client.post(url, {"name": "X"}, content_type="application/json")
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()["code"], "subscription_required")
        self.assertIn("Subscribe", response.json()["error"])

    def test_a_member_is_told_to_ask_an_admin(self):
        expire_trial(self.team)
        self.client.force_login(self.member)
        url = reverse("accounts:api_create_group", args=self.book.url_args)
        response = self.client.post(url, {"name": "X"}, content_type="application/json")
        self.assertEqual(response.status_code, 402)
        self.assertIn("Ask a team admin", response.json()["error"])

    def test_reads_and_the_export_stay_open_and_show_the_banner(self):
        expire_trial(self.team)
        page = self.client.get(reverse("accounts:payee_list", args=self.book.url_args))
        self.assertContains(page, 'data-testid="access-banner"')
        export = self.client.get(reverse("portability:export", args=self.book.url_args))
        self.assertEqual(export.status_code, 200)

    def test_an_outsider_still_gets_the_404_not_the_402(self):
        expire_trial(self.team)
        self.client.force_login(self.outsider)
        url = reverse("accounts:api_create_group", args=self.book.url_args)
        response = self.client.post(url, {"name": "X"}, content_type="application/json")
        self.assertEqual(response.status_code, 404)

    def test_drf_authentication_is_gated_too(self):
        # force_authenticate authenticates inside DRF, so the middleware sees no user.
        expire_trial(self.team)
        api = APIClient()
        api.force_authenticate(user=self.admin)
        url = reverse("journal:journal-entry-list", args=self.book.url_args)
        self.assertEqual(api.post(url, {}, format="json").status_code, 402)
        self.assertEqual(api.get(url).status_code, 200)

    def test_billing_pages_stay_writable(self):
        expire_trial(self.team)
        Team.objects.filter(pk=self.team.pk).update(is_founding_member=False)
        create_stripe_product(STANDARD)
        response = self.client.post(
            reverse("subscriptions_team:create_checkout_session", args=[self.team.slug]), {"priceId": "price_nope"}
        )
        self.assertEqual(response.status_code, 400)  # reached the view: refused for the price, not the gate


class PausedJobsTest(PlaidBookTestCase):
    def test_a_read_only_team_is_not_synced(self):
        expire_trial(self.team)
        with mock.patch.object(plaid_tasks, "_sync_item") as sync:
            result = plaid_tasks.sync_plaid_transactions(self.item.id)
        sync.assert_not_called()
        self.assertEqual(result["status"], "read_only")
        with mock.patch.object(plaid_tasks.sync_plaid_transactions, "apply_async") as queued:
            plaid_tasks.sync_all_plaid_items()
        queued.assert_not_called()

    def test_an_entitled_team_is_synced(self):
        with mock.patch.object(plaid_tasks, "_sync_item", return_value={"success": True}) as sync:
            plaid_tasks.sync_plaid_transactions(self.item.id)
        sync.assert_called_once()


class PausedRecurringTest(RecurringFixture):
    def test_a_read_only_book_catches_up_once_entitled(self):
        r = self.make_rule()
        expire_trial(self.team)
        self.assertEqual(recurring.materialize_due(), 0)
        self.assertFalse(BankTransaction.objects.filter(recurring=r).exists())

        Team.objects.filter(pk=self.team.pk).update(is_complimentary=True)
        self.assertEqual(recurring.materialize_due(), 2)  # Oct 5, Nov 5


@override_settings(STRIPE_FOUNDING_PRODUCT_ID=FOUNDING_ID)
class CheckoutPricesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.standard = create_stripe_product(STANDARD)
        cls.founding = create_stripe_product(
            ProductMetadata(stripe_id=FOUNDING_ID, slug="founding", name="Founding", features=[])
        )
        with override_settings(FOUNDING_MEMBER_LIMIT=1):
            cls.founder = Team.objects.create(name="Founder", slug="founder")
            cls.regular = Team.objects.create(name="Regular", slug="regular")
        cls.user = CustomUser.objects.create_user(username="buyer", password="pass")

    def test_each_team_is_offered_one_product(self):
        self.assertEqual([p.product.id for p in products_for_team(self.founder)], [FOUNDING_ID])
        self.assertEqual([p.product.id for p in products_for_team(self.regular)], [STANDARD.stripe_id])

    def test_a_regular_team_cannot_buy_the_founding_price(self):
        founding_price = self.founding.default_price.id
        self.assertNotIn(founding_price, allowed_price_ids(self.regular))
        with self.assertRaises(PriceNotAllowedError):
            create_stripe_checkout_session(self.regular, founding_price, self.user)

    @override_settings(STRIPE_FOUNDING_PRODUCT_ID="")
    def test_an_unconfigured_founding_product_is_a_config_error_not_the_regular_price(self):
        with self.assertRaises(SubscriptionConfigError):
            products_for_team(self.founder)

    def test_subscribing_mid_trial_keeps_the_rest_of_the_trial(self):
        kwargs = _trial_kwargs(self.regular)
        self.assertEqual(kwargs["trial_end"], int(self.regular.trial_ends_at.timestamp()))
        self.regular.trial_ends_at = timezone.now() + timedelta(hours=47)
        self.assertEqual(_trial_kwargs(self.regular), {})  # Stripe refuses a trial_end under 48h away
