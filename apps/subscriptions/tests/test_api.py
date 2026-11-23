"""Stripe Checkout and Customer Portal session URLs as JSON. Stripe itself is never called."""

import json
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.subscriptions.exceptions import SubscriptionConfigError
from apps.subscriptions.metadata import ProductMetadata
from apps.subscriptions.tests.utils import create_stripe_product
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

PRODUCT = ProductMetadata(
    stripe_id="prod_api_test",
    slug="plan-api",
    name="Plan API",
    features=[],
    price_displays={},
    description="",
    is_default=False,
)
VIEWS = "apps.subscriptions.views.api_views"


class StripeSessionAPITest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Billing", slug="billing")
        cls.admin = CustomUser.objects.create_user(username="admin@billing.test", password="pass")
        cls.member = CustomUser.objects.create_user(username="member@billing.test", password="pass")
        cls.outsider = CustomUser.objects.create_user(username="outsider@billing.test", password="pass")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})
        cls.price = create_stripe_product(PRODUCT).default_price

    def checkout(self, price_id):
        url = reverse("subscriptions_team:api_create_checkout_session", args=[self.team.slug])
        return self.client.post(url, data=json.dumps({"price_id": price_id}), content_type="application/json")

    def portal(self):
        return self.client.post(reverse("subscriptions_team:api_create_portal_session", args=[self.team.slug]))

    @mock.patch(f"{VIEWS}.create_stripe_checkout_session")
    def test_an_admin_gets_a_checkout_url(self, create):
        create.return_value = SimpleNamespace(url="https://checkout.stripe.test/c/pay_123")
        self.client.force_login(self.admin)
        response = self.checkout(self.price.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"url": "https://checkout.stripe.test/c/pay_123"})
        create.assert_called_once_with(self.team, self.price.id, self.admin)

    @mock.patch(f"{VIEWS}.create_stripe_checkout_session")
    def test_an_unknown_price_is_refused(self, create):
        self.client.force_login(self.admin)
        response = self.checkout("price_nope")
        self.assertEqual(response.status_code, 400)
        self.assertIn("price_id", response.json())
        create.assert_not_called()

    @mock.patch(f"{VIEWS}.create_stripe_portal_session")
    def test_an_admin_gets_a_portal_url(self, create):
        create.return_value = SimpleNamespace(url="https://billing.stripe.test/p/session_1")
        self.client.force_login(self.admin)
        response = self.portal()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"url": "https://billing.stripe.test/p/session_1"})

    @mock.patch(f"{VIEWS}.create_stripe_portal_session", side_effect=SubscriptionConfigError("No subscription."))
    def test_no_subscription_is_a_400(self, _create):
        self.client.force_login(self.admin)
        response = self.portal()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"non_field_errors": ["No subscription."]})

    @mock.patch(f"{VIEWS}.create_stripe_portal_session")
    @mock.patch(f"{VIEWS}.create_stripe_checkout_session")
    def test_members_non_members_and_anonymous_are_refused(self, checkout, portal):
        for user in (self.member, self.outsider, None):
            with self.subTest(user=user):
                self.client.logout()
                if user:
                    self.client.force_login(user)
                self.assertEqual(self.checkout(self.price.id).status_code, 403)
                self.assertEqual(self.portal().status_code, 403)
        checkout.assert_not_called()
        portal.assert_not_called()


class ActiveProductsAPITest(TestCase):
    """`GET /subscriptions/api/active-products/`: the plans a client offers before checkout."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(username="plans@billing.test", password="pass")

    @mock.patch(f"{VIEWS}.get_active_products_with_metadata")
    def test_a_signed_in_user_gets_the_plans(self, products):
        products.return_value = [SimpleNamespace(to_dict=lambda: {"metadata": {"slug": "plan-api"}})]
        self.client.force_login(self.user)
        response = self.client.get(reverse("subscriptions:products_api"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"metadata": {"slug": "plan-api"}}])

    def test_anonymous_is_refused(self):
        response = self.client.get(reverse("subscriptions:products_api"))
        self.assertIn(response.status_code, (401, 403))
