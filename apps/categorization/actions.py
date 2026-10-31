"""
What a rule (or any provider) decides about a row besides its category.

The category is *the* decision -- filing it is `categorize.categorize_single`.
Everything else a suggestion carries is a named **decision** in
`Suggestion.decisions` (`{"payee": "Blue Bottle"}`), applied here around the
filing. A rule's decisions come from its action columns (`set_payee`, …).

Adding one -- a business/personal flag, a sales-tax code -- is: a nullable
column on `CategorizationRule`, one `Action` in `ACTIONS`, and a portability
column. The matcher, the pipeline, the apply loop, the API payload and the UI
summary all iterate this list and need no edit.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class Action:
    key: str  # the decision key, in `Suggestion.decisions`
    rule_field: str  # the column on CategorizationRule that holds it
    label: str  # "Rename payee to"
    # Before filing: change the bank row (so the entry and any mirror are created
    # with the new value). After filing: change the entry.
    before: Callable | None = None
    after: Callable | None = None


def _payee_before(row, value):
    row.merchant_name = value


def _payee_after(row, entry, value):
    # The same pairing `batch_edit` writes: the feed row's merchant name and the
    # entry's Payee.
    from apps.accounts.models import Payee

    payee, _created = Payee.objects.get_or_create(book=row.book, name=value)
    if entry.payee_id != payee.id:
        entry.payee = payee
        entry.save()


def _description_before(row, value):
    row.description = value


ACTIONS = (
    Action(key="payee", rule_field="set_payee", label=_("Rename payee to"), before=_payee_before, after=_payee_after),
    Action(
        key="description", rule_field="set_description", label=_("Rename description to"), before=_description_before
    ),
)

ACTIONS_BY_KEY = {action.key: action for action in ACTIONS}


def decisions_from_rule(rule) -> dict:
    """`{decision key: value}` for every action the rule sets."""
    decisions = {}
    for action in ACTIONS:
        value = (getattr(rule, action.rule_field, "") or "").strip()
        if value:
            decisions[action.key] = value
    return decisions


def apply_before(row, decisions) -> bool:
    """Apply every before-filing decision to `row` (unsaved). True when anything changed."""
    changed = False
    for key, value in (decisions or {}).items():
        action = ACTIONS_BY_KEY.get(key)
        if action is None or action.before is None:
            continue  # a decision this build does not know about yet is ignored
        action.before(row, value)
        changed = True
    return changed


def apply_after(row, entry, decisions) -> None:
    for key, value in (decisions or {}).items():
        action = ACTIONS_BY_KEY.get(key)
        if action is not None and action.after is not None:
            action.after(row, entry, value)


def describe(decisions) -> list[str]:
    """Human-readable lines for the UI summary: ["Rename payee to Blue Bottle"]."""
    return [f"{ACTIONS_BY_KEY[key].label} {value}" for key, value in (decisions or {}).items() if key in ACTIONS_BY_KEY]
