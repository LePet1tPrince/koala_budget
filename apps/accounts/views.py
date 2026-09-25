"""
Views for accounts app.
"""

import json
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max, Min, ProtectedError, Q, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.books.decorators import login_and_book_required
from apps.books.helpers import book_display_name
from apps.books.mixins import LoginAndBookRequiredMixin
from apps.journal.models import JournalEntry, JournalLine
from apps.onboarding.services.opening import OPENING_DESCRIPTION
from apps.reconciliation import presenters
from apps.reconciliation.services.signs import is_reconcilable

from .forms import AccountForm, AccountGroupForm, InstitutionForm, PayeeForm
from .models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_CHOICES,
    ACCOUNT_TYPE_EQUITY,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
    Institution,
    Payee,
)
from .navigation import back_link, get_return_to, with_return_to

# Display order and section labels for the chart-of-accounts board
ACCOUNT_TYPE_ORDER = [
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_LIABILITY,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_EQUITY,
]
ACCOUNT_TYPE_SECTION_LABELS = {
    ACCOUNT_TYPE_ASSET: _("Assets"),
    ACCOUNT_TYPE_LIABILITY: _("Liabilities"),
    ACCOUNT_TYPE_INCOME: _("Income"),
    ACCOUNT_TYPE_EXPENSE: _("Expenses"),
    ACCOUNT_TYPE_EQUITY: _("Goals"),
}

FEED_ACCOUNT_TYPES = (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY)

# Display-only section for equity-type groups that hold no goal (opening balances).
SECTION_EQUITY = "equity"


def _account_payload(account, book, goal_left=None):
    """Account row shape shared by the accounts board props and the create API.

    A goal account shows what the goal has `left`, not its raw ledger balance:
    its ledger holds only the spending, while its claim is allocations − spending.
    """
    return {
        "id": account.pk,
        "name": account.name,
        "balance": str(goal_left if goal_left is not None else account.balance),
        "isGoal": goal_left is not None,
        "institution": account.institution.name if account.institution else None,
        "hasFeed": account.has_feed,
        "isSystem": account.is_system,
        "url": account.get_absolute_url(),
        "editUrl": reverse("accounts:account_update", args=[*book.url_args, account.pk]),
    }


def _group_payload(group, accounts=None):
    """Group card shape shared by the accounts board props and the create API."""
    return {
        "id": group.pk,
        "name": group.name,
        "accountType": group.account_type,
        "isSystem": group.is_system,
        "url": group.get_absolute_url(),
        "accounts": accounts if accounts is not None else [],
    }


# Accounts Home View
@method_decorator(ensure_csrf_cookie, name="dispatch")
class AccountsHomeView(LoginAndBookRequiredMixin, TemplateView):
    """Home page for accounts app: drag-and-drop chart-of-accounts board.

    ensure_csrf_cookie: the board POSTs JSON (reorder/create) with the
    X-CSRFToken header, so the cookie must be set even though the page
    renders no <form>.
    """

    template_name = "accounts/accounts_home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "accounts"
        context["accounts_section"] = "accounts"
        context["page_title"] = _("Accounts | {name}").format(name=book_display_name(self.request.book))

        book = self.request.book

        from apps.budget.models import GOALS_GROUP_NAME
        from apps.budget.services import goal_left_by_account

        goal_left = goal_left_by_account(book)
        accounts_by_group = {}
        accounts = (
            Account.objects.filter(book=book)
            .with_balance()
            .select_related("institution")
            .order_by("sort_order", "name")
        )
        for account in accounts:
            accounts_by_group.setdefault(account.account_group_id, []).append(
                _account_payload(account, book, goal_left.get(account.pk))
            )

        # The equity type is stored as "goal" but also holds plain equity (opening
        # balances), so it is shown as two sections: groups holding goals, and the rest.
        sections = {account_type: [] for account_type in (*ACCOUNT_TYPE_ORDER, SECTION_EQUITY)}
        for group in AccountGroup.objects.filter(book=book).order_by("sort_order", "name"):
            accounts_in_group = accounts_by_group.get(group.pk, [])
            key = group.account_type
            if key == ACCOUNT_TYPE_EQUITY and not (
                any(a["isGoal"] for a in accounts_in_group) or (group.name == GOALS_GROUP_NAME and not group.is_system)
            ):
                key = SECTION_EQUITY
            sections[key].append(_group_payload(group, accounts_in_group))

        account_create_url = reverse("accounts:account_create", args=book.url_args)
        types = [
            {
                "key": account_type,
                "accountType": account_type,
                "label": str(ACCOUNT_TYPE_SECTION_LABELS[account_type]),
                "groups": sections[account_type],
            }
            for account_type in ACCOUNT_TYPE_ORDER
        ]
        types[-1]["newGoalUrl"] = reverse("budget:goal_create", args=book.url_args)
        types.append(
            {
                "key": SECTION_EQUITY,
                "accountType": ACCOUNT_TYPE_EQUITY,
                "label": str(_("Equity")),
                "groups": sections[SECTION_EQUITY],
            }
        )
        context["manage_props"] = {
            "types": types,
            "urls": {
                "reorderAccounts": reverse("accounts:api_reorder_accounts", args=book.url_args),
                "reorderGroups": reverse("accounts:api_reorder_groups", args=book.url_args),
                "createAccount": reverse("accounts:api_create_account", args=book.url_args),
                "createGroup": reverse("accounts:api_create_group", args=book.url_args),
                "accountCreatePage": account_create_url,
            },
        }
        return context


# Shared by the management pages
SECTION_LABELS_BY_TYPE = {
    **ACCOUNT_TYPE_SECTION_LABELS,
    ACCOUNT_TYPE_EQUITY: _("Goals & equity"),
}

# Accounts whose natural balance is a credit: shown as cr - dr, so a card's debt and
# a salary read positive, matching the balance sheet and the activity table.
CREDIT_NORMAL_TYPES = (ACCOUNT_TYPE_LIABILITY, ACCOUNT_TYPE_INCOME, ACCOUNT_TYPE_EQUITY)


def natural_amount(amount, account_type):
    """A dr - cr amount signed the way the account type is read."""
    return -amount if account_type in CREDIT_NORMAL_TYPES else amount


def _account_rows(request, accounts, account_type=None):
    """
    Rows for an account table on a group or institution page, plus the column label.

    Balance-type accounts show today's balance. Income and expense accounts have
    no meaningful balance, only activity, so they show this year's total. A goal
    shows what it has left, as on the accounts board.
    """
    from datetime import date

    from apps.budget.services import goal_left_by_account
    from apps.journal.models import counted_entries

    period_types = (ACCOUNT_TYPE_INCOME, ACCOUNT_TYPE_EXPENSE)
    accounts = accounts.select_related("account_group", "institution").with_balance()
    if account_type in period_types:
        year_start = date.today().replace(month=1, day=1)
        in_year = counted_entries("journal_lines__journal_entry__") & Q(
            journal_lines__journal_entry__entry_date__gte=year_start
        )
        accounts = accounts.annotate(
            _year=Coalesce(Sum("journal_lines__dr_amount", filter=in_year), Decimal("0"))
            - Coalesce(Sum("journal_lines__cr_amount", filter=in_year), Decimal("0"))
        )
    goal_left = goal_left_by_account(request.book) if account_type in (None, ACCOUNT_TYPE_EQUITY) else {}

    rows = []
    for account in accounts:
        kind = account.account_group.account_type
        if account.pk in goal_left:
            amount = goal_left[account.pk]
        elif kind in period_types:
            amount = natural_amount(account._year, kind)
        else:
            amount = natural_amount(account.balance, kind)
        is_liability = kind == ACCOUNT_TYPE_LIABILITY
        tag = None
        if is_liability and amount:
            tag = _("owed") if amount > 0 else _("in credit")
        rows.append(
            {
                "account": account,
                "url": reverse("accounts:account_detail", args=[*request.book.url_args, account.pk]),
                "amount": amount,
                "is_liability": is_liability,
                # A debt reads as its size plus "owed" / "in credit", never as a red negative
                "display": abs(amount) if is_liability else amount,
                "negative": amount < 0 and not is_liability,
                "tag": tag,
            }
        )

    if account_type in period_types:
        label = _("This year")
    elif goal_left and all(row["account"].pk in goal_left for row in rows):
        label = _("Left")
    else:
        label = _("Balance")
    return rows, label


class ManageSectionMixin(LoginAndBookRequiredMixin):
    """Context shared by the chart-of-accounts management pages."""

    accounts_section = None
    title = None
    list_url_name = None
    back_label = None
    new_title = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "accounts"
        context["accounts_section"] = self.accounts_section
        context["page_title"] = _("{title} | {name}").format(
            title=self.title, name=book_display_name(self.request.book)
        )
        return context


class BookFormMixin:
    """Pass the book to the form (for its duplicate-name check) and save into it."""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["book"] = self.request.book
        return kwargs

    def form_valid(self, form):
        form.instance.book = self.request.book
        return super().form_valid(form)


class ReturnToMixin:
    """
    Keep `?return_to` across an edit: Save lands on the detail page with it still
    attached, so that page's back link still goes where it did.
    """

    def get_success_url(self):
        return with_return_to(self.object.get_absolute_url(), get_return_to(self.request))


class FormPageMixin:
    """
    The standalone create/edit page: the no-JS path behind the dialogs, and where a
    rejected submit lands to show its errors. Editing goes back (and cancels) to the
    item's page, `return_to` intact; creating goes back to the list.
    """

    template_name = "accounts/object_form.html"
    form_testid = "object-form"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = getattr(self, "object", None)
        if obj is not None and obj.pk:
            return_to = get_return_to(self.request)
            detail_url = with_return_to(obj.get_absolute_url(), return_to)
            context["form_title"] = _("Edit “%(name)s”") % {"name": obj.name}
            context["cancel_url"] = detail_url
            context["back"] = {"url": detail_url, "label": _("Back to %(name)s") % {"name": obj.name}}
            context["return_to"] = return_to
        else:
            list_url = reverse(self.list_url_name, args=self.request.book.url_args)
            context["form_title"] = self.new_title
            context["cancel_url"] = list_url
            context["back"] = {"url": list_url, "label": self.back_label}
        context["form_testid"] = self.form_testid
        return context


class DetailPageMixin:
    """Back link, edit form and return path for a detail page."""

    form_class = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return_to = get_return_to(self.request)
        context["return_to"] = return_to
        context["back"] = back_link(
            self.request, reverse(self.list_url_name, args=self.request.book.url_args), self.back_label
        )
        context["here"] = self.request.get_full_path()
        args = [*self.request.book.url_args, self.object.pk]
        model_name = self.model._meta.model_name
        context["edit_url"] = with_return_to(reverse(f"accounts:{model_name}_update", args=args), return_to)
        context["delete_url"] = reverse(f"accounts:{model_name}_delete", args=args)
        if self.form_class:
            context["edit_form"] = self.form_class(instance=self.object, book=self.request.book)
        return context


class DeleteGuardMixin:
    """
    Delete from the detail page's dialog. A GET (the no-JS path) still renders the
    confirm page; a delete the object's references forbid is refused with a
    message instead of reaching the database's PROTECT as a 500.
    """

    template_name = "accounts/confirm_delete.html"

    def delete_blocked_reason(self, obj):
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["blocked_reason"] = self.delete_blocked_reason(self.object)
        context["cancel_url"] = self.object.get_absolute_url()
        return context

    def form_valid(self, form):
        reason = self.delete_blocked_reason(self.object)
        if reason:
            messages.error(self.request, reason)
            return redirect(self.object.get_absolute_url())
        name = str(self.object)
        response = super().form_valid(form)
        messages.success(self.request, _("Deleted “%(name)s”.") % {"name": name})
        return response

    def get_success_url(self):
        return reverse(self.list_url_name, args=self.request.book.url_args)


def _group_delete_blocked_reason(group):
    if group.is_system:
        return _("System account groups cannot be deleted.")
    count = group.accounts.count()
    if count:
        return ngettext(
            "“%(name)s” still has %(count)d account. Move it to another group or delete it first.",
            "“%(name)s” still has %(count)d accounts. Move them to another group or delete them first.",
            count,
        ) % {"name": group.name, "count": count}
    return None


def _payee_delete_blocked_reason(payee):
    count = payee.journal_entries.count()
    if count:
        return ngettext(
            "“%(name)s” is on %(count)d transaction, so it can't be deleted. Rename it instead, "
            "or change the payee on that transaction first.",
            "“%(name)s” is on %(count)d transactions, so it can't be deleted. Rename it instead, "
            "or change the payee on those transactions first.",
            count,
        ) % {"name": payee.name, "count": count}
    return None


# Account Group Views
class AccountGroupViewMixin(ManageSectionMixin):
    """Mixin class for all AccountGroup views."""

    model = AccountGroup
    accounts_section = "groups"
    title = _("Account Groups")
    list_url_name = "accounts:accountgroup_list"
    back_label = _("Back to Groups")
    new_title = _("New group")


class AccountGroupListView(AccountGroupViewMixin, ListView):
    """Account groups, sectioned by type in board order."""

    def get_queryset(self):
        return AccountGroup.objects.filter(book=self.request.book).annotate(account_count=Count("accounts"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        by_type = {}
        for group in context["object_list"]:
            by_type.setdefault(group.account_type, []).append(group)
        context["sections"] = [
            {"label": SECTION_LABELS_BY_TYPE[account_type], "groups": by_type[account_type]}
            for account_type in ACCOUNT_TYPE_ORDER
            if account_type in by_type
        ]
        context["create_form"] = AccountGroupForm(book=self.request.book)
        return context


class AccountGroupCreateView(AccountGroupViewMixin, BookFormMixin, FormPageMixin, CreateView):
    """Create a new account group."""

    form_class = AccountGroupForm


class AccountGroupDetailView(AccountGroupViewMixin, DetailPageMixin, DetailView):
    """An account group and the accounts in it."""

    form_class = AccountGroupForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        group = self.object
        rows, amount_label = _account_rows(
            self.request, group.accounts.order_by("sort_order", "name"), group.account_type
        )
        context["rows"] = rows
        context["amount_label"] = amount_label
        context["total"] = sum((row["amount"] for row in rows), Decimal("0"))
        context["blocked_reason"] = _group_delete_blocked_reason(group)
        context["add_account_url"] = (
            reverse("accounts:account_create", args=self.request.book.url_args)
            + "?"
            + urlencode({"account_type": group.account_type, "account_group": group.pk})
        )
        return context


class AccountGroupUpdateView(AccountGroupViewMixin, BookFormMixin, ReturnToMixin, FormPageMixin, UpdateView):
    """Update an account group."""

    form_class = AccountGroupForm


class AccountGroupDeleteView(AccountGroupViewMixin, DeleteGuardMixin, DeleteView):
    """Delete an account group (refused while it has accounts, or is a system group)."""

    def delete_blocked_reason(self, obj):
        return _group_delete_blocked_reason(obj)


# Account Views
class AccountViewMixin(ManageSectionMixin):
    """Mixin class for all Account views."""

    model = Account
    accounts_section = "accounts"
    title = _("Accounts")
    list_url_name = "accounts:accounts_home"
    back_label = _("Back to Accounts")
    new_title = _("New account")


class AccountCreateView(AccountViewMixin, CreateView):
    """Create a new account."""

    form_class = AccountForm
    template_name = "accounts/account_create.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["book"] = self.request.book
        kwargs["is_create"] = True
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["account_types_with_groups"] = [
            {
                "value": value,
                "label": label,
                "groups": list(AccountGroup.for_book.filter(account_type=value)),
            }
            for value, label in ACCOUNT_TYPE_CHOICES
        ]
        context["initial_type"] = self.request.GET.get("account_type", "")
        context["initial_group"] = self.request.GET.get("account_group", "")
        context["initial_institution"] = self.request.GET.get("institution", "")
        # Opened from a group or institution page: Save, Cancel and Back return there.
        back = back_link(
            self.request, reverse("accounts:accounts_home", args=self.request.book.url_args), _("Back to Accounts")
        )
        context["return_to"] = get_return_to(self.request)
        context["cancel_url"] = back["url"]
        context["back_label"] = back["label"]
        return context

    def get_success_url(self):
        return with_return_to(self.object.get_absolute_url(), get_return_to(self.request))

    def form_valid(self, form):
        form.instance.book = self.request.book
        account_group = form.cleaned_data.get("account_group")
        if account_group:
            form.instance.has_feed = account_group.account_type in (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY)
            if account_group.account_type not in (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY):
                form.instance.institution = None

        response = super().form_valid(form)

        if self.request.POST.get("next_action") == "save_and_create_another":
            params = {
                "account_type": form.cleaned_data.get("account_type", ""),
                "account_group": form.instance.account_group_id or "",
            }
            if form.instance.institution_id:
                params["institution"] = form.instance.institution_id
            if return_to := get_return_to(self.request):
                params["return_to"] = return_to
            url = reverse("accounts:account_create", args=self.request.book.url_args)
            return redirect(f"{url}?{urlencode(params)}")

        return response


class AccountDetailView(AccountViewMixin, DetailView):
    """An account: what it is, its statements, and its activity over a date range."""

    def get_queryset(self):
        return Account.objects.filter(book=self.request.book).select_related("account_group", "institution")

    def get_context_data(self, **kwargs):
        from datetime import date, datetime

        from apps.reports.services import ReportService

        context = super().get_context_data(**kwargs)
        account = self.object
        book = self.request.book

        # Activity section (same components as the reports drill-down):
        # date range from ?start_date/?end_date, defaulting to this year --
        # matches the "year" default the date-range picker sets client-side
        # (data-default-range="year" on account_detail.html).
        try:
            start_date = datetime.strptime(self.request.GET.get("start_date", ""), "%Y-%m-%d").date()
            end_date = datetime.strptime(self.request.GET.get("end_date", ""), "%Y-%m-%d").date()
        except ValueError:
            today = date.today()
            start_date = today.replace(month=1, day=1)
            end_date = today

        service = ReportService(book)
        report_data = service.get_account_activity(account, start_date, end_date)
        context["report_data"] = report_data
        context["balance_chart_data"] = ReportService.build_balance_chart_data(report_data, start_date, end_date)
        context["budget_chart_data"] = service.get_budget_vs_actual_chart_data(account, start_date, end_date)
        context["start_date"] = start_date
        context["end_date"] = end_date
        # Statement history for accounts a statement can confirm (assets and liabilities).
        if is_reconcilable(account):
            context["statements"] = presenters.history_payload(account)[:6]
            context["reconcilable"] = True

        return_to = get_return_to(self.request)
        context["back"] = back_link(
            self.request, reverse("accounts:accounts_home", args=book.url_args), _("Back to Accounts")
        )
        context["here"] = self.request.get_full_path()
        context["edit_url"] = with_return_to(
            reverse("accounts:account_update", args=[*book.url_args, account.pk]), return_to
        )
        account_type = account.account_group.account_type
        if report_data["is_balance_account"]:
            balance = natural_amount(account.balance, account_type)
            is_liability = account_type == ACCOUNT_TYPE_LIABILITY
            # A card paid past zero owes nothing: say "in credit" rather than a red negative debt
            label = _("Balance")
            if is_liability:
                label = _("Balance owed") if balance >= 0 else _("In credit")
            context["current_balance"] = {
                "label": label,
                "amount": abs(balance) if is_liability else balance,
                "negative": balance < 0 and not is_liability,
            }
        if account.has_feed:
            context["feed_url"] = (
                reverse("bank_feed:bank_feed_home", args=book.url_args) + "?" + urlencode({"account": account.pk})
            )
        return context


class AccountUpdateView(AccountViewMixin, ReturnToMixin, FormPageMixin, UpdateView):
    """Update an account."""

    form_class = AccountForm
    form_testid = "account-form"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["book"] = self.request.book
        return kwargs


class AccountDeleteView(AccountViewMixin, DeleteView):
    """
    Delete an account.

    Confirmation is a dialog on the account detail page, not a separate page --
    this view only ever handles the POST it submits. A GET (a stale bookmark,
    a direct hit) has nothing to render, so it just bounces back to the detail
    page rather than serving the old standalone confirm page.
    """

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        return redirect(self.object.get_absolute_url())

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.is_system:
            messages.error(request, _("System accounts cannot be deleted."))
            return redirect(obj.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("accounts:accounts_home", args=self.request.book.url_args)

    def _blocking_journal_entries(self, account):
        """
        Journal entries referencing this account that are *not* its own opening
        balance -- real activity the user needs to know about before it's gone.

        An opening balance entry is exactly the shape `create_opening_balances`
        writes: two lines, one on this account and the other on the book's system
        equity offset. Anything else -- a categorized transaction, a transfer leg,
        a split -- blocks the delete rather than being silently discarded.
        """
        entry_ids = JournalLine.objects.filter(account=account).values_list("journal_entry_id", flat=True).distinct()
        entries = JournalEntry.objects.filter(pk__in=entry_ids).prefetch_related("lines__account__account_group")

        opening_ids = []
        blocking = []
        for entry in entries:
            lines = list(entry.lines.all())
            other_lines = [line for line in lines if line.account_id != account.id]
            is_opening = (
                len(lines) == 2
                and len(other_lines) == 1
                and str(entry.description).startswith(str(OPENING_DESCRIPTION))
                and other_lines[0].account.is_system
                and other_lines[0].account.account_group.account_type == ACCOUNT_TYPE_EQUITY
            )
            if is_opening:
                opening_ids.append(entry.pk)
            else:
                blocking.append(entry)

        return opening_ids, blocking

    def _warn_has_transactions(self):
        # extra_tags="modal" -- messages.html renders this as a dialog popup
        # instead of the auto-dismissing toast, since it needs to actually be read.
        messages.error(
            self.request,
            _("Please delete all associated transactions before deleting an account."),
            extra_tags="modal",
        )

    def form_valid(self, form):
        self.object = self.get_object()
        success_url = self.get_success_url()

        opening_entry_ids, blocking_entries = self._blocking_journal_entries(self.object)
        if blocking_entries:
            self._warn_has_transactions()
            return redirect(self.object.get_absolute_url())

        try:
            with transaction.atomic():
                if opening_entry_ids:
                    JournalEntry.objects.filter(pk__in=opening_entry_ids).delete()
                self.object.delete()
        except ProtectedError:
            self._warn_has_transactions()
            return redirect(self.object.get_absolute_url())

        return redirect(success_url)


# Payee Views
class PayeeViewMixin(ManageSectionMixin):
    """Mixin class for all Payee views."""

    model = Payee
    accounts_section = "payees"
    title = _("Payees")
    list_url_name = "accounts:payee_list"
    back_label = _("Back to Payees")
    new_title = _("New payee")


def _payee_usage(queryset):
    """Annotate how often (and how recently) each payee's transactions count."""
    from apps.journal.models import counted_entries

    counted = counted_entries("journal_entries__")
    return queryset.annotate(
        transaction_count=Count("journal_entries", filter=counted),
        first_used=Min("journal_entries__entry_date", filter=counted),
        last_used=Max("journal_entries__entry_date", filter=counted),
    )


class PayeeListView(PayeeViewMixin, ListView):
    """Payees, with how often each is used."""

    def get_queryset(self):
        return _payee_usage(Payee.objects.filter(book=self.request.book)).order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["create_form"] = PayeeForm(book=self.request.book)
        return context


class PayeeCreateView(PayeeViewMixin, BookFormMixin, FormPageMixin, CreateView):
    """Create a new payee."""

    form_class = PayeeForm


# Recent transactions listed on a payee's page; the rest are a click away on Transactions.
PAYEE_RECENT_LIMIT = 25


class PayeeDetailView(PayeeViewMixin, DetailPageMixin, DetailView):
    """A payee: how it's used and its recent transactions."""

    form_class = PayeeForm

    def get_queryset(self):
        return _payee_usage(Payee.objects.filter(book=self.request.book))

    def get_context_data(self, **kwargs):
        from apps.journal.models import counted_entries

        context = super().get_context_data(**kwargs)
        payee = self.object
        entries = (
            JournalEntry.objects.filter(book=self.request.book, payee=payee)
            .filter(counted_entries())
            .prefetch_related("lines__account__account_group")
            .order_by("-entry_date", "-pk")[:PAYEE_RECENT_LIMIT]
        )
        url_args = self.request.book.url_args

        def link(account):
            return {"name": account.name, "url": reverse("accounts:account_detail", args=[*url_args, account.pk])}

        recent = []
        for entry in entries:
            lines = entry.lines.all()
            on_feed = [line.account.account_group.account_type in FEED_ACCOUNT_TYPES for line in lines]
            recent.append(
                {
                    "entry": entry,
                    # What the money was for, then the bank account or card it moved through
                    "categories": [link(line.account) for line, feed in zip(lines, on_feed, strict=True) if not feed],
                    "accounts": [link(line.account) for line, feed in zip(lines, on_feed, strict=True) if feed],
                    "amount": sum((line.dr_amount for line in lines), Decimal("0")),
                }
            )
        context["recent"] = recent
        context["transactions_url"] = (
            reverse("journal:transactions_home", args=self.request.book.url_args)
            + "?"
            + urlencode({"f_payee": payee.name})
        )
        context["blocked_reason"] = _payee_delete_blocked_reason(payee)
        return context


class PayeeUpdateView(PayeeViewMixin, BookFormMixin, ReturnToMixin, FormPageMixin, UpdateView):
    """Rename a payee."""

    form_class = PayeeForm


class PayeeDeleteView(PayeeViewMixin, DeleteGuardMixin, DeleteView):
    """Delete a payee (refused while any transaction uses it)."""

    def delete_blocked_reason(self, obj):
        return _payee_delete_blocked_reason(obj)


# Institution Views
class InstitutionViewMixin(ManageSectionMixin):
    """Mixin class for all Institution views."""

    model = Institution
    accounts_section = "institutions"
    title = _("Institutions")
    list_url_name = "accounts:institution_list"
    back_label = _("Back to Institutions")
    new_title = _("New institution")


class InstitutionListView(InstitutionViewMixin, ListView):
    """Institutions, with their accounts' net balance."""

    def get_queryset(self):
        return Institution.objects.filter(book=self.request.book).annotate(account_count=Count("accounts"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        net = {}
        for account in Account.objects.filter(book=self.request.book, institution__isnull=False).with_balance():
            net[account.institution_id] = net.get(account.institution_id, Decimal("0")) + account.balance
        for institution in context["object_list"]:
            institution.net_balance = net.get(institution.pk, Decimal("0"))
        context["create_form"] = InstitutionForm(book=self.request.book)
        return context


class InstitutionCreateView(InstitutionViewMixin, BookFormMixin, FormPageMixin, CreateView):
    """Create a new institution."""

    form_class = InstitutionForm


class InstitutionDetailView(InstitutionViewMixin, DetailPageMixin, DetailView):
    """An institution and the accounts held there."""

    form_class = InstitutionForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        institution = self.object
        rows, _label = _account_rows(self.request, institution.accounts.order_by("account_group__account_type"))
        context["rows"] = rows
        # Assets less what is owed there: the dr - cr sum, un-flipped
        context["net_balance"] = sum(
            (-row["amount"] if row["is_liability"] else row["amount"] for row in rows), Decimal("0")
        )
        context["add_account_url"] = (
            reverse("accounts:account_create", args=self.request.book.url_args)
            + "?"
            + urlencode({"account_type": ACCOUNT_TYPE_ASSET, "institution": institution.pk})
        )
        return context


class InstitutionUpdateView(InstitutionViewMixin, BookFormMixin, ReturnToMixin, FormPageMixin, UpdateView):
    """Rename an institution."""

    form_class = InstitutionForm


class InstitutionDeleteView(InstitutionViewMixin, DeleteGuardMixin, DeleteView):
    """Delete an institution; its accounts are kept and simply unlinked (SET_NULL)."""


# =============================================================================
# JSON API for the drag-and-drop chart-of-accounts board
# =============================================================================


def _json_body(request):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@login_and_book_required
@require_POST
def api_reorder_accounts(request, team_slug, book_slug):
    """Persist account ordering (and group moves) from the board.

    Body: {"groups": [{"group_id": int, "account_ids": [int, ...]}, ...]}
    Each entry is the full ordered list of accounts now in that group; an account
    listed under a different group than its current one is moved there (same
    account type only). All-or-nothing.
    """
    payload = _json_body(request)
    if payload is None or not isinstance(payload.get("groups"), list) or len(payload["groups"]) > 100:
        return JsonResponse({"error": _("Invalid request body.")}, status=400)

    group_ids = []
    placements = {}  # account_id -> (group_id, position)
    for entry in payload["groups"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("account_ids"), list):
            return JsonResponse({"error": _("Invalid request body.")}, status=400)
        group_ids.append(entry.get("group_id"))
        for position, account_id in enumerate(entry["account_ids"]):
            if account_id in placements:
                return JsonResponse({"error": _("An account appears more than once.")}, status=400)
            placements[account_id] = (entry.get("group_id"), position)

    groups = {g.pk: g for g in AccountGroup.objects.filter(book=request.book, pk__in=group_ids)}
    if len(groups) != len(set(group_ids)):
        return JsonResponse({"error": _("Unknown account group.")}, status=400)

    accounts = {
        a.pk: a for a in Account.objects.filter(book=request.book, pk__in=placements).select_related("account_group")
    }
    if len(accounts) != len(placements):
        return JsonResponse({"error": _("Unknown account.")}, status=400)

    moved = 0
    for account_id, (group_id, position) in placements.items():
        account = accounts[account_id]
        group = groups[group_id]
        if account.account_group_id != group_id:
            if account.account_group.account_type != group.account_type:
                return JsonResponse(
                    {"error": _("Accounts can only be moved between groups of the same type.")}, status=400
                )
            moved += 1
        account.account_group = group
        account.sort_order = position

    with transaction.atomic():
        Account.objects.bulk_update(accounts.values(), ["account_group", "sort_order"], batch_size=500)

    if moved:
        log_event(
            AuditEvent.BULK_EDIT,
            request=request,
            metadata={"scope": "accounts_board", "action": "move_account", "moved": moved},
        )
    return JsonResponse({"ok": True})


@login_and_book_required
@require_POST
def api_reorder_groups(request, team_slug, book_slug):
    """Persist account-group ordering within one account type.

    Body: {"account_type": str, "group_ids": [int, ...]}
    """
    payload = _json_body(request)
    if payload is None or not isinstance(payload.get("group_ids"), list):
        return JsonResponse({"error": _("Invalid request body.")}, status=400)

    account_type = payload.get("account_type")
    if account_type not in dict(ACCOUNT_TYPE_CHOICES):
        return JsonResponse({"error": _("Invalid account type.")}, status=400)

    group_ids = payload["group_ids"]
    groups = {
        g.pk: g for g in AccountGroup.objects.filter(book=request.book, account_type=account_type, pk__in=group_ids)
    }
    if len(groups) != len(group_ids) or len(set(group_ids)) != len(group_ids):
        return JsonResponse({"error": _("Unknown account group.")}, status=400)

    for position, group_id in enumerate(group_ids):
        groups[group_id].sort_order = position

    with transaction.atomic():
        AccountGroup.objects.bulk_update(groups.values(), ["sort_order"], batch_size=500)
    return JsonResponse({"ok": True})


@login_and_book_required
@require_POST
def api_create_account(request, team_slug, book_slug):
    """Create an account at the bottom of a group (board inline "+" form).

    Body: {"name": str, "group_id": int}
    """
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": _("Invalid request body.")}, status=400)

    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 200:
        return JsonResponse({"error": _("Enter an account name (max 200 characters).")}, status=400)

    group = AccountGroup.objects.filter(book=request.book, pk=payload.get("group_id")).first()
    if group is None:
        return JsonResponse({"error": _("Unknown account group.")}, status=400)

    # Same uniqueness rule as AccountForm: name must be unique within the account type
    if Account.objects.filter(book=request.book, name=name, account_group__account_type=group.account_type).exists():
        return JsonResponse(
            {
                "error": _("An account named '%(name)s' already exists for account type '%(type)s'.")
                % {"name": name, "type": dict(ACCOUNT_TYPE_CHOICES)[group.account_type]}
            },
            status=400,
        )

    with transaction.atomic():
        next_order = Account.objects.filter(book=request.book, account_group=group).aggregate(m=Max("sort_order"))["m"]
        account = Account.objects.create(
            book=request.book,
            name=name,
            account_group=group,
            has_feed=group.account_type in FEED_ACCOUNT_TYPES,
            sort_order=0 if next_order is None else next_order + 1,
        )
    return JsonResponse({"account": _account_payload(account, request.book)}, status=201)


@login_and_book_required
@require_POST
def api_create_group(request, team_slug, book_slug):
    """Create an account group at the bottom of a type section (board inline "+" form).

    Body: {"name": str, "account_type": str}
    """
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": _("Invalid request body.")}, status=400)

    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 200:
        return JsonResponse({"error": _("Enter a group name (max 200 characters).")}, status=400)

    account_type = payload.get("account_type")
    if account_type not in dict(ACCOUNT_TYPE_CHOICES):
        return JsonResponse({"error": _("Invalid account type.")}, status=400)

    if AccountGroup.objects.filter(book=request.book, name=name).exists():
        return JsonResponse({"error": _("A group named '%(name)s' already exists.") % {"name": name}}, status=400)

    with transaction.atomic():
        next_order = AccountGroup.objects.filter(book=request.book, account_type=account_type).aggregate(
            m=Max("sort_order")
        )["m"]
        group = AccountGroup.objects.create(
            book=request.book,
            name=name,
            account_type=account_type,
            sort_order=0 if next_order is None else next_order + 1,
        )
    return JsonResponse({"group": _group_payload(group)}, status=201)
