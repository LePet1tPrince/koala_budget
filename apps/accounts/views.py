"""
Views for accounts app.
"""

from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from apps.books.helpers import book_display_name
from apps.books.mixins import LoginAndBookRequiredMixin
from apps.journal.models import JournalEntry
from apps.reconciliation import presenters
from apps.reconciliation.services.signs import is_reconcilable

from .board import ACCOUNT_TYPE_ORDER, ACCOUNT_TYPE_SECTION_LABELS
from .forms import AccountForm, AccountGroupForm, InstitutionForm, PayeeForm
from .models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_BUDGET,
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
from .services import (
    SYSTEM_ACCOUNT_MESSAGE,
    delete_account,
    group_delete_blocked_reason,
    institution_account_sections,
    natural_amount,
    payee_delete_blocked_reason,
    payee_usage,
    set_institution_accounts,
)
from .validators import FEED_ACCOUNT_TYPES


# Accounts Home View
@method_decorator(ensure_csrf_cookie, name="dispatch")
class AccountsHomeView(LoginAndBookRequiredMixin, TemplateView):
    """Home page for accounts app: drag-and-drop chart-of-accounts board.

    The board loads and writes through the board API (`AccountsBoardViewSet`).
    ensure_csrf_cookie: those writes send the X-CSRFToken header, so the cookie
    must be set even though the page renders no <form>.
    """

    template_name = "accounts/accounts_home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "accounts"
        context["accounts_section"] = "accounts"
        context["page_title"] = _("Accounts | {name}").format(name=book_display_name(self.request.book))
        return context


# Shared by the management pages
SECTION_LABELS_BY_TYPE = {
    **ACCOUNT_TYPE_SECTION_LABELS,
    ACCOUNT_TYPE_EQUITY: _("Goals & equity"),
}


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
    """Back link, edit and delete URLs (the no-JS pages behind the editor) and return path for a detail page."""

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
        return context


class DeleteGuardMixin:
    """
    The no-JS delete (the detail page's editor deletes through the API). A GET
    renders the confirm page; a delete the object's references forbid is refused with a
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


# Account Group Views
class AccountGroupViewMixin(ManageSectionMixin):
    """Mixin class for all AccountGroup views."""

    model = AccountGroup
    accounts_section = "groups"
    title = _("Account Groups")
    list_url_name = "accounts:accountgroup_list"
    back_label = _("Back to Groups")
    new_title = _("New group")

    def get_queryset(self):
        # The budget group belongs to the app (apps.budget.buckets): no page of its own.
        return super().get_queryset().exclude(account_type=ACCOUNT_TYPE_BUDGET)


class AccountGroupListView(AccountGroupViewMixin, ListView):
    """Account groups, sectioned by type in board order."""

    def get_queryset(self):
        return (
            AccountGroup.objects.filter(book=self.request.book)
            .exclude(account_type=ACCOUNT_TYPE_BUDGET)
            .annotate(account_count=Count("accounts"))
        )

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
        return context


class AccountGroupCreateView(AccountGroupViewMixin, BookFormMixin, FormPageMixin, CreateView):
    """Create a new account group."""

    form_class = AccountGroupForm


class AccountGroupDetailView(AccountGroupViewMixin, DetailPageMixin, DetailView):
    """An account group and the accounts in it."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        group = self.object
        rows, amount_label = _account_rows(
            self.request, group.accounts.order_by("sort_order", "name"), group.account_type
        )
        context["rows"] = rows
        context["amount_label"] = amount_label
        context["total"] = sum((row["amount"] for row in rows), Decimal("0"))
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
        return group_delete_blocked_reason(obj)


# Account Views
class AccountViewMixin(ManageSectionMixin):
    """Mixin class for all Account views."""

    model = Account
    accounts_section = "accounts"
    title = _("Accounts")
    list_url_name = "accounts:accounts_home"
    back_label = _("Back to Accounts")
    new_title = _("New account")

    def get_queryset(self):
        # Budget buckets belong to the app (apps.budget.buckets): no page of their own.
        return super().get_queryset().exclude_budget_buckets()


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


@method_decorator(ensure_csrf_cookie, name="dispatch")
class AccountDetailView(AccountViewMixin, DetailView):
    """
    An account: what it is, its statements, and its activity over a date range.

    ensure_csrf_cookie: the activity edit modal PATCHes the transactions API
    with the token read from the cookie.
    """

    def get_queryset(self):
        return super().get_queryset().select_related("account_group", "institution")

    def get_context_data(self, **kwargs):
        from datetime import date

        from apps.reports.services import ReportService
        from apps.reports.timeframes import date_range_from_request

        context = super().get_context_data(**kwargs)
        account = self.object
        book = self.request.book

        # Activity section (same components as the reports drill-down): date range
        # from ?start_date/?end_date, else the book's report timeframe, else this year.
        # The picker reflects whatever this resolves to (data-start-date on the page).
        today = date.today()
        start_date, end_date = date_range_from_request(self.request, (today.replace(month=1, day=1), today))

        service = ReportService(book)
        report_data = service.get_account_activity(account, start_date, end_date)
        context["report_data"] = report_data
        context["has_balance_chart"] = report_data["is_balance_account"]
        context["budget_chart_kind"] = service.budget_chart_kind(account)
        if context["has_balance_chart"] or context["budget_chart_kind"]:
            # The charts draw from the `AccountViewSet.charts` body for this range, built
            # from the activity above and embedded rather than fetched again.
            from .api import account_charts_payload

            context["charts_json"] = account_charts_payload(service, account, report_data, start_date, end_date)
        context["start_date"] = start_date
        context["end_date"] = end_date
        # Statement history for accounts a statement can confirm (assets and liabilities).
        if is_reconcilable(account):
            context["statements"] = presenters.history_payload(account)[:6]
            context["reconcilable"] = True

        from apps.budget.models import GoalAccountLink

        context["feeds_goal"] = GoalAccountLink.objects.open().filter(account=account).select_related("goal").first()

        # Activity rows open the Transactions page's edit modal, which loads its
        # pickers from `journal:transaction-pickers`.

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
            messages.error(request, SYSTEM_ACCOUNT_MESSAGE)
            return redirect(obj.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("accounts:accounts_home", args=self.request.book.url_args)

    def form_valid(self, form):
        self.object = self.get_object()
        reason = delete_account(self.object)
        if reason:
            # extra_tags="modal" -- messages.html renders this as a dialog popup
            # instead of the auto-dismissing toast, since it needs to actually be read.
            messages.error(self.request, reason, extra_tags="modal")
            return redirect(self.object.get_absolute_url())
        return redirect(self.get_success_url())


# Payee Views
class PayeeViewMixin(ManageSectionMixin):
    """Mixin class for all Payee views."""

    model = Payee
    accounts_section = "payees"
    title = _("Payees")
    list_url_name = "accounts:payee_list"
    back_label = _("Back to Payees")
    new_title = _("New payee")


class PayeeListView(PayeeViewMixin, ListView):
    """Payees, with how often each is used."""

    def get_queryset(self):
        return payee_usage(Payee.objects.filter(book=self.request.book)).order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context


class PayeeCreateView(PayeeViewMixin, BookFormMixin, FormPageMixin, CreateView):
    """Create a new payee."""

    form_class = PayeeForm


# Recent transactions listed on a payee's page; the rest are a click away on Transactions.
PAYEE_RECENT_LIMIT = 25


class PayeeDetailView(PayeeViewMixin, DetailPageMixin, DetailView):
    """A payee: how it's used and its recent transactions."""

    def get_queryset(self):
        return payee_usage(Payee.objects.filter(book=self.request.book))

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
        return context


class PayeeUpdateView(PayeeViewMixin, BookFormMixin, ReturnToMixin, FormPageMixin, UpdateView):
    """Rename a payee."""

    form_class = PayeeForm


class PayeeDeleteView(PayeeViewMixin, DeleteGuardMixin, DeleteView):
    """Delete a payee (refused while any transaction uses it)."""

    def delete_blocked_reason(self, obj):
        return payee_delete_blocked_reason(obj)


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
        return context


class InstitutionCreateView(InstitutionViewMixin, BookFormMixin, FormPageMixin, CreateView):
    """Create a new institution."""

    form_class = InstitutionForm


class InstitutionDetailView(InstitutionViewMixin, DetailPageMixin, DetailView):
    """An institution and the accounts held there."""

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
        context["choose_accounts_url"] = with_return_to(
            reverse("accounts:institution_accounts", args=[*self.request.book.url_args, institution.pk]),
            context["return_to"],
        )
        return context


class InstitutionAccountsView(InstitutionViewMixin, DetailView):
    """
    Pick, from one checklist, which accounts are held at an institution.

    The detail page opens the same form in a dialog; this GET is its no-JS page.
    The POST names every account that should be linked here: a ticked account is
    linked (moving it from any other institution), an unticked one linked here is
    unlinked. Accounts the checklist does not offer are never touched.
    """

    template_name = "accounts/institution_accounts.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return_to = get_return_to(self.request)
        detail_url = with_return_to(self.object.get_absolute_url(), return_to)
        context["sections"] = institution_account_sections(self.object)
        context["return_to"] = return_to
        context["cancel_url"] = detail_url
        context["back"] = {"url": detail_url, "label": _("Back to %(name)s") % {"name": self.object.name}}
        return context

    def post(self, request, *args, **kwargs):
        institution = self.object = self.get_object()
        if set_institution_accounts(institution, request.POST.getlist("accounts")):
            count = institution.accounts.count()
            messages.success(
                request,
                ngettext(
                    "Saved. “%(name)s” now holds %(count)d account.",
                    "Saved. “%(name)s” now holds %(count)d accounts.",
                    count,
                )
                % {"name": institution.name, "count": count},
            )
        return redirect(with_return_to(institution.get_absolute_url(), get_return_to(request)))


class InstitutionUpdateView(InstitutionViewMixin, BookFormMixin, ReturnToMixin, FormPageMixin, UpdateView):
    """Rename an institution."""

    form_class = InstitutionForm


class InstitutionDeleteView(InstitutionViewMixin, DeleteGuardMixin, DeleteView):
    """Delete an institution; its accounts are kept and simply unlinked (SET_NULL)."""
