from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def currency(value):
    """
    Format a number as a currency amount: 1234.5 -> "$1,234.50", -3 -> "-$3.00".

    Falls back to the raw value for non-numeric input so a template never breaks.
    """
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"
