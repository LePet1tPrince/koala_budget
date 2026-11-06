"""How the budget page words and colours an Available figure. The templates (via
`budget_tags`) and the auto-save response (`views._budget_cells`) both read it, so a
repaint can't show a figure differently from the first render."""

from decimal import Decimal

from django.utils.translation import gettext as _

from apps.web.templatetags.currency_tags import currency

TONE_NEG = "neg"
TONE_POS = "pos"
# Income budgeted but not received yet: expected, not a shortfall, so no red.
TONE_EXPECTED = "expected"

TONE_CLASSES = {TONE_NEG: "text-error", TONE_POS: "text-success", TONE_EXPECTED: "text-base-content/70"}


def tone(amount) -> str:
    if amount < 0:
        return TONE_NEG
    if amount > 0:
        return TONE_POS
    return ""


def available_display(amount, income=False) -> tuple[str, str]:
    """(text, tone) for an Available figure. An income category's negative Available is
    budgeted income that hasn't arrived: "$1,200.00 still expected", neutral."""
    amount = Decimal(str(amount))
    if income and amount < 0:
        return _("%(amount)s still expected") % {"amount": currency(-amount)}, TONE_EXPECTED
    return currency(amount), tone(amount)


def tone_class(value: str) -> str:
    return TONE_CLASSES.get(value, "")
