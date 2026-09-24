from copy import copy

from django.conf import settings

from .meta import absolute_url, get_server_root


def project_meta(request):
    # modify these values as needed and add whatever else you want globally available here
    project_data = copy(settings.PROJECT_METADATA)
    project_data["TITLE"] = "{} | {}".format(project_data["NAME"], project_data["DESCRIPTION"])
    return {
        "project_meta": project_data,
        "server_url": get_server_root(),
        "page_url": absolute_url(request.path),
        "page_title": "",
        "page_description": "",
        "page_image": "",
        "light_theme": settings.LIGHT_THEME,
        "dark_theme": settings.DARK_THEME,
        "current_theme": request.COOKIES.get("theme", ""),
        "dark_mode": request.COOKIES.get("theme", "") == settings.DARK_THEME,
        "turnstile_key": getattr(settings, "TURNSTILE_KEY", None),
        "use_i18n": getattr(settings, "USE_I18N", False) and len(getattr(settings, "LANGUAGES", [])) > 1,
    }


def google_analytics_id(request):
    """
    Adds google analytics id to all requests
    """
    if settings.GOOGLE_ANALYTICS_ID:
        return {
            "GOOGLE_ANALYTICS_ID": settings.GOOGLE_ANALYTICS_ID,
        }
    else:
        return {}


# Sidebar sub-items, keyed by the view they point at. A view listed here shades
# its sub-item rather than the parent (Reports, Accounts); a view that is not
# listed leaves the parent's own `active_tab` shading in charge.
NAV_ITEMS_BY_VIEW = {
    "monthly_review:home": "monthly-review",
    "reports:dollar_map": "report-dollar-map",
    "reports:income_statement": "report-income-statement",
    "reports:balance_sheet": "report-balance-sheet",
    "reports:net_worth_trend": "report-net-worth-trend",
    "reports:cash_flow": "report-cash-flow",
    "reports:budget_vs_actual": "report-budget-vs-actual",
    "reports:goal_progress": "report-goal-progress",
    "accounts:accounts_home": "accounts-list",
}

# Whole families of views that belong to one sub-item (detail/create/edit pages).
NAV_ITEMS_BY_PREFIX = (
    ("reconciliation:", "report-reconciliation"),
    ("accounts:account_", "accounts-list"),
    ("accounts:accountgroup_", "accounts-groups"),
    ("accounts:payee_", "accounts-payees"),
    ("accounts:institution_", "accounts-institutions"),
)


def nav_item(request):
    """
    The sidebar sub-item for the current page, as `nav_item`, or "" when the
    page has none. `active_tab` says which top-level section is open; this says
    which of its sub-items to shade.
    """
    match = getattr(request, "resolver_match", None)
    view_name = match.view_name if match else ""
    item = NAV_ITEMS_BY_VIEW.get(view_name, "")
    if not item:
        item = next((key for prefix, key in NAV_ITEMS_BY_PREFIX if view_name.startswith(prefix)), "")
    # The account drill-down names the page it was opened from; the budget page
    # has no report sub-item, so that one shades nothing.
    if view_name == "reports:account_activity":
        item = {
            "balance_sheet": "report-balance-sheet",
            "budget": "",
        }.get(request.GET.get("source"), "report-income-statement")
    return {"nav_item": item}
