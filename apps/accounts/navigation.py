"""
Where a page's back link goes.

A detail page can be reached from many places -- the accounts board, a report
drill-down, another account's activity, a group or an institution. A link into it
carries `?return_to=<the linking page's path>` and the page's back link returns
there, labelled for that page; without one it falls back to the page's own parent
(the board, or the Groups/Payees/Institutions list).

`return_to` is read from the query string, so it survives the date-range picker
(which rewrites only its own params) and is passed on through Edit and Cancel.
Following a chain works for free: account B opened from account A's activity
carries A's full path, A's own `return_to` included.
"""

from urllib.parse import urlencode, urlsplit

from django.urls import Resolver404, resolve
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _

RETURN_TO_PARAM = "return_to"

# Past this a chain of hops has stopped meaning anything; fall back to the parent.
MAX_RETURN_TO_LENGTH = 2000


def get_return_to(request):
    """The request's `return_to`, if it is a same-site path; otherwise None."""
    value = request.GET.get(RETURN_TO_PARAM) or request.POST.get(RETURN_TO_PARAM) or ""
    if not value.startswith("/") or value.startswith("//") or len(value) > MAX_RETURN_TO_LENGTH:
        return None
    if not url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}):
        return None
    return value


def with_return_to(url, return_to):
    """`url` carrying `return_to` along, when there is one."""
    if not return_to:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode({RETURN_TO_PARAM: return_to})}"


def _named(model_path, template=None):
    """Label for a page about one object, looked up in the request's book."""

    def build(request, kwargs):
        from django.apps import apps

        model = apps.get_model(model_path)
        pk = kwargs.get("pk") or kwargs.get("account_id")
        obj = model.objects.filter(book=request.book, pk=pk).only("name").first() if pk else None
        if obj is None:
            return _("Back")
        return (template() if template else _("Back to %(name)s")) % {"name": obj.name}

    return build


# url name -> label (or a callable building one from the resolved kwargs)
BACK_LABELS = {
    "accounts:accounts_home": lambda r, k: _("Back to Accounts"),
    "accounts:accountgroup_list": lambda r, k: _("Back to Groups"),
    "accounts:payee_list": lambda r, k: _("Back to Payees"),
    "accounts:institution_list": lambda r, k: _("Back to Institutions"),
    "accounts:account_detail": _named("accounts.Account"),
    "accounts:accountgroup_detail": _named("accounts.AccountGroup"),
    "accounts:payee_detail": _named("accounts.Payee"),
    "accounts:institution_detail": _named("accounts.Institution"),
    # The report drill-down and the account's own page share a name, so say which
    "reports:account_activity": _named("accounts.Account", lambda: _("Back to %(name)s report")),
    "reports:income_statement": lambda r, k: _("Back to Income Statement"),
    "reports:balance_sheet": lambda r, k: _("Back to Balance Sheet"),
    "reports:budget_vs_actual": lambda r, k: _("Back to Budget vs Actual"),
    "reports:reports_home": lambda r, k: _("Back to Reports"),
    "budget:budget_home": lambda r, k: _("Back to Budget"),
    "journal:transactions_home": lambda r, k: _("Back to Transactions"),
    "bank_feed:bank_feed_home": lambda r, k: _("Back to Inbox"),
    "reconciliation:hub": lambda r, k: _("Back to Reconcile"),
    "reconciliation:account": lambda r, k: _("Back to Reconcile"),
}


def _label_for(request, path):
    try:
        match = resolve(urlsplit(path).path)
    except Resolver404:
        return _("Back")
    build = BACK_LABELS.get(match.view_name)
    return build(request, match.kwargs) if build else _("Back")


def back_link(request, default_url, default_label):
    """`{"url", "label"}` for a page's back link: `return_to` if present, else the parent."""
    return_to = get_return_to(request)
    if return_to:
        return {"url": return_to, "label": _label_for(request, return_to)}
    return {"url": default_url, "label": default_label}
