"""
The chart-of-accounts review step: preview what the answers produced, and apply
whatever the user changed about it.

**The server stays authoritative.** The client does not post a chart of accounts;
it posts *edits* against the one the server generated -- a set of removals,
renames and additions. That difference matters: a wholesale list would let a
client invent an account in the system equity group, flip `is_system`, or attach
an account to a group that no answer created. Edits can only ever be applied to
the server's own generated set, so none of that is expressible.

Rebuilding the template from the stored answers on both the preview and the apply
means the two can never disagree about what the base was.
"""

from dataclasses import dataclass

from django.utils.translation import gettext as _

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
)

MAX_NAME_LENGTH = 200

# Asset and liability accounts are the ones a bank reports, so they get a feed.
FEED_ACCOUNT_TYPES = (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY)

# The order types are shown in, and a one-line explanation of each. The review
# screen is most users' first encounter with double-entry vocabulary.
TYPE_ORDER = (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY, ACCOUNT_TYPE_INCOME, ACCOUNT_TYPE_EXPENSE)

# Plural, because each heading labels a list. `ACCOUNT_TYPE_CHOICES` is singular
# ("Asset"), which reads as a database value rather than a section of a chart.
TYPE_LABELS = {
    ACCOUNT_TYPE_ASSET: _("Assets"),
    ACCOUNT_TYPE_LIABILITY: _("Debts"),
    ACCOUNT_TYPE_INCOME: _("Income"),
    ACCOUNT_TYPE_EXPENSE: _("Spending"),
}

TYPE_BLURBS = {
    ACCOUNT_TYPE_ASSET: _("What you own — the money and things you have."),
    ACCOUNT_TYPE_LIABILITY: _("What you owe — cards, loans, the mortgage."),
    ACCOUNT_TYPE_INCOME: _("Where money comes in."),
    ACCOUNT_TYPE_EXPENSE: _("Where money goes out."),
}


class ReviewError(ValueError):
    """An edit the user cannot be allowed to make. The message is user-facing."""


@dataclass(frozen=True)
class Edits:
    removed: tuple[str, ...] = ()
    renamed: tuple[tuple[str, str], ...] = ()
    added: tuple[tuple[str, str], ...] = ()  # (group name, account name)

    @property
    def is_empty(self) -> bool:
        return not (self.removed or self.renamed or self.added)


def parse_edits(raw) -> Edits:
    """
    Read an edit payload defensively. Anything malformed is dropped rather than
    raising: a client that sends nonsense gets the unedited chart, not an error.
    """
    if not isinstance(raw, dict):
        return Edits()

    # The list check matters: a bare string here would iterate character by
    # character and be read as a request to remove accounts named "R", "e", "n"...
    removed_raw = raw.get("removed", [])
    removed = tuple(n for n in removed_raw if isinstance(n, str)) if isinstance(removed_raw, list) else ()

    renamed_raw = raw.get("renamed", {})
    renamed = (
        tuple((k, v) for k, v in renamed_raw.items() if isinstance(k, str) and isinstance(v, str))
        if isinstance(renamed_raw, dict)
        else ()
    )

    added_raw = raw.get("added", [])
    added = (
        tuple(
            (a["group"], a["name"])
            for a in added_raw
            if isinstance(a, dict) and isinstance(a.get("group"), str) and isinstance(a.get("name"), str)
        )
        if isinstance(added_raw, list)
        else ()
    )

    return Edits(removed=removed, renamed=renamed, added=added)


def _type_by_group(template: dict) -> dict[str, str]:
    return {g["name"]: g["type"] for g in template["account_groups"]}


def _check_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ReviewError(_("An account needs a name."))
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ReviewError(_("Account names are limited to %(n)d characters.") % {"n": MAX_NAME_LENGTH})
    return cleaned


def apply_edits(template: dict, edits: Edits) -> dict:
    """
    Return the template with the user's edits applied.

    Raises `ReviewError` with a user-facing message on anything invalid; the
    caller turns that into a 400 and nothing is written.
    """
    group_types = _type_by_group(template)
    accounts = [dict(a) for a in template["accounts"]]

    removed = set(edits.removed)
    renames = dict(edits.renamed)

    # Removals -------------------------------------------------------------
    kept = []
    for account in accounts:
        if account["name"] not in removed:
            kept.append(account)
            continue
        if account["is_system"]:
            # Reconciliation and opening-balance entries post against it; without
            # it those features have nothing to balance to.
            raise ReviewError(
                _("'%(name)s' is needed for reconciliation and cannot be removed.") % {"name": account["name"]}
            )
    accounts = kept

    # Renames --------------------------------------------------------------
    for account in accounts:
        if account["name"] in renames:
            account["name"] = _check_name(renames[account["name"]])

    # Additions ------------------------------------------------------------
    for group_name, raw_name in edits.added:
        if group_name not in group_types:
            raise ReviewError(_("Unknown account group '%(group)s'.") % {"group": group_name})
        accounts.append(
            {
                "number": None,
                "name": _check_name(raw_name),
                "group": group_name,
                "has_feed": group_types[group_name] in FEED_ACCOUNT_TYPES,
                "is_system": False,
                # Added accounts sort after the generated ones in their group.
                "sort_order": 9000,
            }
        )

    _reject_duplicates(accounts, group_types)

    # A group everything was removed from would show up empty on the accounts
    # board, so drop it rather than create it.
    used_groups = {a["group"] for a in accounts}
    groups = [g for g in template["account_groups"] if g["name"] in used_groups]

    return {**template, "account_groups": groups, "accounts": accounts}


def _reject_duplicates(accounts: list[dict], group_types: dict[str, str]) -> None:
    """
    Account names are unique per account *type*, not per team -- the same rule
    `AccountForm` and the accounts board enforce. Catching it here means the
    whole edit is refused with a clear message instead of failing halfway
    through `get_or_create`.
    """
    seen: dict[tuple[str, str], str] = {}
    for account in accounts:
        key = (group_types[account["group"]], account["name"].casefold())
        if key in seen:
            raise ReviewError(
                _("You have two accounts named '%(name)s'. Names must be unique within a type.")
                % {"name": account["name"]}
            )
        seen[key] = account["name"]


def grouped_for_review(template: dict) -> list[dict]:
    """
    The template arranged for display: type → group → accounts.

    System accounts are left out. They exist to balance reconciliation entries,
    the user cannot remove them, and explaining them at this point costs more
    than it is worth.
    """
    sections = []
    for account_type in TYPE_ORDER:
        groups = []
        for group in template["account_groups"]:
            if group["type"] != account_type:
                continue
            names = [a["name"] for a in template["accounts"] if a["group"] == group["name"] and not a["is_system"]]
            if names:
                groups.append({"name": group["name"], "accounts": names})

        if groups:
            sections.append(
                {
                    "type": account_type,
                    "label": str(TYPE_LABELS[account_type]),
                    "blurb": str(TYPE_BLURBS[account_type]),
                    "groups": groups,
                    "count": sum(len(g["accounts"]) for g in groups),
                }
            )

    # Groups outside TYPE_ORDER (equity) hold only system accounts, so they never
    # produce a section.
    return sections
