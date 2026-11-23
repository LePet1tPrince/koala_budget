"""Tests for apps.emails: the send path, each alert, unsubscribe and the preferences page and API."""

import re
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from allauth.account.models import EmailAddress
from dateutil.relativedelta import relativedelta
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from djstripe import enums
from djstripe.models import Subscription

from apps.accounts.models import Account, AccountGroup
from apps.budget.ledger import set_budget
from apps.journal.models import JournalEntry, JournalLine
from apps.plaid import item_status
from apps.plaid.models import PlaidItem
from apps.subscriptions.tests.utils import create_customer
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

from .. import alerts, kinds, services, tasks
from ..models import EmailPreferences, SentEmail


def make_user(email, verified=True, **extra):
    user = CustomUser.objects.create_user(username=email, email=email, password="pw-123456!", **extra)
    EmailAddress.objects.create(user=user, email=email, verified=verified, primary=True)
    return user


class EmailFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Koala House", slug="koala-house")
        cls.book = cls.team.default_book
        cls.admin = make_user("admin@example.com")
        cls.member = make_user("member@example.com")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})

    def recipients(self):
        return sorted(address for message in mail.outbox for address in message.to)


class SendTest(EmailFixture):
    def test_sends_once_per_key(self):
        self.assertTrue(services.send(self.admin, kinds.TRIAL_ENDING, {"team": self.team}, keys=["k1"]))
        self.assertFalse(services.send(self.admin, kinds.TRIAL_ENDING, {"team": self.team}, keys=["k1"]))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(SentEmail.objects.filter(user=self.admin, kind=kinds.TRIAL_ENDING).count(), 1)

    def test_a_new_key_among_old_ones_sends(self):
        services.send(self.admin, kinds.TRIAL_ENDING, {"team": self.team}, keys=["a"])
        self.assertTrue(services.send(self.admin, kinds.TRIAL_ENDING, {"team": self.team}, keys=["a", "b"]))
        self.assertEqual(len(mail.outbox), 2)

    def test_keys_are_required(self):
        with self.assertRaises(ValueError):
            services.send(self.admin, kinds.TRIAL_ENDING, {}, keys=[])

    def test_unconfirmed_address_gets_nothing(self):
        user = make_user("new@example.com", verified=False)
        self.assertFalse(services.send(user, kinds.TRIAL_ENDING, {"team": self.team}, keys=["k"]))
        self.assertEqual(mail.outbox, [])

    @override_settings(ACCOUNT_EMAIL_VERIFICATION="none")
    def test_unconfirmed_address_is_fine_when_the_site_never_confirms(self):
        user = make_user("new@example.com", verified=False)
        self.assertTrue(services.send(user, kinds.TRIAL_ENDING, {"team": self.team}, keys=["k"]))

    def test_inactive_account_gets_nothing(self):
        user = make_user("gone@example.com", is_active=False)
        self.assertFalse(services.send(user, kinds.TRIAL_ENDING, {"team": self.team}, keys=["k"]))

    def test_an_optional_kind_turned_off_is_not_sent(self):
        EmailPreferences.objects.create(user=self.member, budget_alerts=False)
        context = {"book": self.book, "month": date(2026, 11, 1), "rows": []}
        self.assertFalse(services.send(self.member, kinds.BUDGET_OVERSPENT, context, keys=["k"]))
        self.assertFalse(SentEmail.objects.exists())

    def test_a_failed_send_leaves_no_record_so_a_retry_sends(self):
        failing = mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp down"))
        with failing, self.assertRaises(OSError):
            services.send(self.admin, kinds.TRIAL_ENDING, {"team": self.team}, keys=["k"])
        self.assertFalse(SentEmail.objects.exists())
        self.assertTrue(services.send(self.admin, kinds.TRIAL_ENDING, {"team": self.team}, keys=["k"]))

    def test_optional_email_carries_one_click_unsubscribe(self):
        context = {"book": self.book, "month": date(2026, 11, 1), "rows": []}
        services.send(self.member, kinds.BUDGET_OVERSPENT, context, keys=["k"])
        message = mail.outbox[0]
        self.assertEqual(message.extra_headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        link = re.search(r"<(.+)>", message.extra_headers["List-Unsubscribe"]).group(1)
        self.assertIn("/emails/unsubscribe/", link)
        self.assertIn(link, message.body)
        self.assertIn(link, message.alternatives[0][0])

    def test_billing_email_has_no_unsubscribe(self):
        services.send(self.admin, kinds.TRIAL_ENDING, {"team": self.team}, keys=["k"])
        message = mail.outbox[0]
        self.assertNotIn("List-Unsubscribe", message.extra_headers)
        self.assertIn("/emails/preferences/", message.body)

    def test_subject_is_one_line(self):
        services.send(self.admin, kinds.TRIAL_ENDING, {"team": self.team}, keys=["k"])
        self.assertEqual(mail.outbox[0].subject, "Your Koala Budget trial ends soon")


class TokenTest(EmailFixture):
    def test_round_trip(self):
        token = services.unsubscribe_token(self.member, kinds.PREF_BUDGET)
        self.assertEqual(services.read_unsubscribe_token(token), (self.member.pk, kinds.PREF_BUDGET))

    def test_tampered_token_is_rejected(self):
        token = services.unsubscribe_token(self.member, kinds.PREF_BUDGET)
        self.assertIsNone(services.read_unsubscribe_token(token[:-2] + "xx"))

    def test_a_token_for_another_purpose_is_rejected(self):
        from django.core import signing

        other = signing.dumps({"u": self.member.pk, "p": "is_superuser"}, salt=services.UNSUBSCRIBE_SALT)
        self.assertIsNone(services.read_unsubscribe_token(other))
        self.assertIsNone(services.read_unsubscribe_token(signing.dumps({"u": self.member.pk, "p": "budget_alerts"})))


class BankConnectionTest(EmailFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.item = PlaidItem.objects.create(
            book=cls.book, plaid_item_id="item-1", access_token="access-sandbox-1", institution_name="Tangerine"
        )

    def set_status(self, status, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            item_status.set_status(self.item, status, **kwargs)

    def test_login_required_emails_every_member(self):
        self.set_status(PlaidItem.STATUS_LOGIN_REQUIRED, error_code="ITEM_LOGIN_REQUIRED")
        self.assertEqual(self.recipients(), ["admin@example.com", "member@example.com"])
        message = mail.outbox[0]
        self.assertEqual(message.subject, "Tangerine needs you to sign in again")
        self.assertIn(reverse("bank_feed:bank_feed_home", args=self.book.url_args), message.body)

    def test_once_per_status_per_day(self):
        self.set_status(PlaidItem.STATUS_LOGIN_REQUIRED)
        self.set_status(PlaidItem.STATUS_HEALTHY)
        self.set_status(PlaidItem.STATUS_LOGIN_REQUIRED)
        self.assertEqual(len(mail.outbox), 2)

    def test_a_repeat_status_is_not_a_change(self):
        self.set_status(PlaidItem.STATUS_ERROR, error_message="Bank says no")
        self.set_status(PlaidItem.STATUS_ERROR, error_message="Bank says no")
        self.assertEqual(len(mail.outbox), 2)  # one per member, once
        self.assertIn("Bank says no", mail.outbox[0].body)

    def test_healthy_sends_nothing(self):
        self.item.status = PlaidItem.STATUS_ERROR
        self.item.save()
        self.set_status(PlaidItem.STATUS_HEALTHY)
        self.assertEqual(mail.outbox, [])

    def test_fixed_before_the_task_ran_sends_nothing(self):
        self.item.status = PlaidItem.STATUS_HEALTHY
        self.item.save()
        self.assertEqual(alerts.bank_connection(self.item.pk, PlaidItem.STATUS_LOGIN_REQUIRED), 0)

    def test_member_who_turned_it_off_is_skipped(self):
        EmailPreferences.objects.create(user=self.member, bank_connection_alerts=False)
        self.set_status(PlaidItem.STATUS_REVOKED)
        self.assertEqual(self.recipients(), ["admin@example.com"])

    def test_an_archived_book_sends_nothing(self):
        self.book.is_archived = True
        self.book.save()
        self.set_status(PlaidItem.STATUS_LOGIN_REQUIRED)
        self.assertEqual(mail.outbox, [])

    def test_the_item_webhook_path_emails(self):
        with self.captureOnCommitCallbacks(execute=True):
            item_status.handle_item_webhook(
                self.item, "PENDING_EXPIRATION", {"consent_expiration_time": "2026-12-01T00:00:00Z"}
            )
        self.assertEqual(mail.outbox[0].subject, "Your connection to Tangerine is about to expire")

    def test_another_teams_members_are_not_emailed(self):
        other = Team.objects.create(name="Other", slug="other")
        outsider = make_user("outsider@example.com")
        other.members.add(outsider, through_defaults={"role": ROLE_ADMIN})
        self.set_status(PlaidItem.STATUS_LOGIN_REQUIRED)
        self.assertNotIn("outsider@example.com", self.recipients())


class OverspendTest(EmailFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        book = cls.book
        asset = AccountGroup.objects.create(book=book, name="Cash", account_type="asset")
        equity = AccountGroup.objects.create(book=book, name="Opening", account_type="equity")
        expense = AccountGroup.objects.create(book=book, name="Living", account_type="expense")
        cls.checking = Account.objects.create(book=book, name="Checking", account_group=asset)
        cls.opening = Account.objects.create(book=book, name="Opening Balance", account_group=equity)
        cls.groceries = Account.objects.create(book=book, name="Groceries", account_group=expense)
        cls.fun = Account.objects.create(book=book, name="Fun", account_group=expense)
        cls.month = timezone.localdate().replace(day=1)
        cls.post(cls.month, cls.checking, cls.opening, "5000")
        set_budget(book, cls.groceries, cls.month, Decimal("100"))
        set_budget(book, cls.fun, cls.month, Decimal("50"))

    @classmethod
    def post(cls, day, debit, credit, amount):
        entry = JournalEntry.objects.create(book=cls.book, entry_date=day, description="entry", status="posted")
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=debit, dr_amount=Decimal(amount))
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=credit, cr_amount=Decimal(amount))

    def spend(self, category, amount, day=None):
        self.post(day or self.month, category, self.checking, amount)

    def test_overspent_category_emails_the_team_once(self):
        self.spend(self.groceries, "150")
        self.assertEqual(alerts.budget_overspent(self.book), 2)
        message = mail.outbox[0]
        self.assertIn("a category is overspent", message.subject)
        self.assertIn("Groceries: $50.00 over", message.body)
        self.assertNotIn("Fun", message.body)
        self.assertEqual(alerts.budget_overspent(self.book), 0)

    def test_a_newly_overspent_category_sends_again_listing_both(self):
        self.spend(self.groceries, "150")
        alerts.budget_overspent(self.book)
        self.spend(self.fun, "60")
        self.assertEqual(alerts.budget_overspent(self.book), 2)
        latest = mail.outbox[-1]
        self.assertIn("2 categories are overspent", latest.subject)
        self.assertIn("Groceries", latest.body)
        self.assertIn("Fun: $10.00 over", latest.body)

    def test_within_budget_sends_nothing(self):
        self.spend(self.groceries, "100")
        self.assertEqual(alerts.budget_overspent(self.book), 0)

    def test_overspending_carried_in_with_nothing_spent_this_month_is_not_news(self):
        last_month = self.month - relativedelta(months=1)
        self.post(last_month, self.checking, self.opening, "1")
        set_budget(self.book, self.groceries, last_month, Decimal("10"))
        self.spend(self.groceries, "40", day=last_month)  # -30 rolls in
        set_budget(self.book, self.groceries, self.month, Decimal("0"))
        self.assertEqual(alerts.overspent_categories(self.book, self.month), [])

    def test_a_book_without_a_budget_sends_nothing(self):
        other = Team.objects.create(name="No Budget", slug="no-budget")
        self.assertEqual(alerts.budget_overspent(other.default_book), 0)

    def test_the_daily_task_covers_open_books(self):
        self.spend(self.groceries, "150")
        self.assertEqual(tasks.send_overspend_alerts(), 2)
        self.book.is_archived = True
        self.book.save()
        self.spend(self.fun, "60")
        self.assertEqual(tasks.send_overspend_alerts(), 0)

    def test_scheduled(self):
        from django.conf import settings

        self.assertEqual(
            settings.SCHEDULED_TASKS["overspend-alerts"]["task"], "apps.emails.tasks.send_overspend_alerts"
        )


class BillingTest(EmailFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.customer = create_customer()
        now = timezone.now()
        cls.subscription = Subscription.objects.create(
            id="sub_test_1",
            collection_method=enums.InvoiceCollectionMethod.charge_automatically,
            livemode=False,
            status=enums.SubscriptionStatus.active,
            current_period_start=now - relativedelta(months=1),
            current_period_end=now + relativedelta(months=11),
            customer=cls.customer,
        )
        cls.team.customer = cls.customer
        cls.team.subscription = cls.subscription
        cls.team.save()
        cls.trial_end = int((now + timedelta(days=3)).timestamp())

    def invoice(self, **extra):
        return {
            "id": "in_1",
            "subscription": "sub_test_1",
            "customer": self.customer.id,
            "amount_due": 5900,
            "currency": "cad",
            "attempt_count": 1,
            "next_payment_attempt": self.trial_end,
            "hosted_invoice_url": "https://invoice.stripe.com/i/test",
            "lines": {"data": [{"price": {"recurring": {"interval": "year"}}}]},
            **extra,
        }

    def test_trial_ending_goes_to_admins_only(self):
        sent = alerts.trial_ending({"id": "sub_test_1", "customer": self.customer.id, "trial_end": self.trial_end})
        self.assertEqual(sent, 1)
        self.assertEqual(self.recipients(), ["admin@example.com"])
        self.assertIn(reverse("subscriptions_team:subscription_details", args=[self.team.slug]), mail.outbox[0].body)

    def test_trial_ending_skipped_when_cancelled(self):
        payload = {"id": "sub_test_1", "trial_end": self.trial_end, "cancel_at_period_end": True}
        self.assertEqual(alerts.trial_ending(payload), 0)

    def test_billing_ignores_optional_preferences(self):
        EmailPreferences.objects.create(user=self.admin, bank_connection_alerts=False, budget_alerts=False)
        self.assertEqual(alerts.payment_failed(self.invoice()), 1)

    def test_payment_failed_once_per_attempt(self):
        alerts.payment_failed(self.invoice())
        alerts.payment_failed(self.invoice())
        alerts.payment_failed(self.invoice(attempt_count=2))
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("$59.00 CAD", mail.outbox[0].body)
        self.assertIn("https://invoice.stripe.com/i/test", mail.outbox[0].body)

    def test_found_by_customer_when_the_subscription_is_unknown(self):
        self.assertEqual(alerts.payment_failed(self.invoice(subscription="sub_other")), 1)

    def test_unknown_customer_sends_nothing(self):
        self.assertEqual(alerts.payment_failed(self.invoice(subscription=None, customer="cus_nobody")), 0)

    def test_annual_renewal_reminder(self):
        self.assertEqual(alerts.renewal_upcoming(self.invoice(id=None)), 1)
        self.assertIn("renews soon", mail.outbox[0].subject)

    def test_monthly_renewal_is_not_reminded(self):
        invoice = self.invoice(lines={"data": [{"price": {"recurring": {"interval": "month"}}}]})
        self.assertEqual(alerts.renewal_upcoming(invoice), 0)

    def test_renewal_skipped_during_trial_or_when_cancelling(self):
        Subscription.objects.filter(id="sub_test_1").update(status=enums.SubscriptionStatus.trialing)
        self.assertEqual(alerts.renewal_upcoming(self.invoice()), 0)
        Subscription.objects.filter(id="sub_test_1").update(
            status=enums.SubscriptionStatus.active, cancel_at_period_end=True
        )
        self.assertEqual(alerts.renewal_upcoming(self.invoice()), 0)

    def test_webhook_receiver_queues_the_email(self):
        from apps.subscriptions.webhooks import email_admins_about_billing

        event = mock.Mock(type="invoice.payment_failed", data={"object": self.invoice()})
        with self.captureOnCommitCallbacks(execute=True):
            email_admins_about_billing(event=event)
        self.assertEqual(self.recipients(), ["admin@example.com"])


class UnsubscribeViewTest(EmailFixture):
    def url(self, token=None):
        token = token or services.unsubscribe_token(self.member, kinds.PREF_BUDGET)
        return reverse("emails:unsubscribe", args=[token])

    def test_get_asks_and_changes_nothing(self):
        response = self.client.get(self.url())
        self.assertContains(response, "Stop sending overspending alerts to m•••••@example.com?")
        self.assertTrue(EmailPreferences.for_user(self.member).budget_alerts)

    def test_post_turns_it_off_without_signing_in(self):
        response = Client(enforce_csrf_checks=True).post(self.url())
        self.assertContains(response, 'data-testid="unsubscribe-done"')
        prefs = EmailPreferences.objects.get(user=self.member)
        self.assertFalse(prefs.budget_alerts)
        self.assertTrue(prefs.bank_connection_alerts)

    def test_one_click_post(self):
        response = Client(enforce_csrf_checks=True).post(
            self.url(), data="List-Unsubscribe=One-Click", content_type="application/x-www-form-urlencoded"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EmailPreferences.objects.get(user=self.member).budget_alerts)

    def test_bad_token(self):
        response = self.client.post(self.url("not-a-token"))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(EmailPreferences.objects.exists())

    def test_token_for_a_deleted_user(self):
        url = self.url()
        self.member.delete()
        self.assertEqual(self.client.post(url).status_code, 400)


class PreferencesPageTest(EmailFixture):
    def test_requires_sign_in(self):
        response = self.client.get(reverse("emails:preferences"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("account_login"), response["Location"])

    def test_shows_and_saves(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("emails:preferences"))
        self.assertContains(response, 'data-testid="pref-budget"')
        self.assertContains(response, 'data-testid="settings-nav-emails"')
        response = self.client.post(reverse("emails:preferences"), {"bank_connection_alerts": "on"})
        self.assertRedirects(response, reverse("emails:preferences"))
        prefs = EmailPreferences.objects.get(user=self.member)
        self.assertTrue(prefs.bank_connection_alerts)
        self.assertFalse(prefs.budget_alerts)

    def test_saves_only_your_own(self):
        self.client.force_login(self.member)
        self.client.post(reverse("emails:preferences"), {"user": self.admin.pk})
        self.assertFalse(EmailPreferences.objects.filter(user=self.admin).exists())


class PreferencesApiTest(EmailFixture):
    url = reverse("emails:api_preferences")

    def test_anonymous_is_refused(self):
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_get_defaults_and_patch(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url).json(), {"bank_connection_alerts": True, "budget_alerts": True})
        response = self.client.patch(self.url, {"budget_alerts": False}, content_type="application/json")
        self.assertEqual(response.json(), {"bank_connection_alerts": True, "budget_alerts": False})
        self.assertFalse(EmailPreferences.objects.get(user=self.member).budget_alerts)

    def test_api_key_cannot_change_preferences(self):
        from apps.api.models import UserAPIKey

        _key, secret = UserAPIKey.objects.create_key(name="k", user=self.member)
        response = Client().patch(
            self.url, {"budget_alerts": False}, content_type="application/json", HTTP_AUTHORIZATION=f"Api-Key {secret}"
        )
        self.assertIn(response.status_code, (401, 403))
        self.assertFalse(EmailPreferences.objects.filter(user=self.member).exists())
