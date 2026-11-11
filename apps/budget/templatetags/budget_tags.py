from django import template

from apps.budget.display import available_display, tone_class

register = template.Library()


@register.filter
def available_text(amount, income=False):
    """An Available figure as the budget page shows it (income still to arrive reads "still expected")."""
    return available_display(amount, income)[0]


@register.filter
def available_class(amount, income=False):
    """The colour class for an Available figure: red/green by sign, neutral for income still expected."""
    return tone_class(available_display(amount, income)[1])
