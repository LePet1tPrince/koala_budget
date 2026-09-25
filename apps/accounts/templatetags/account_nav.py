"""Links that bring the user back: see `apps.accounts.navigation`."""

from django import template

from apps.accounts.navigation import with_return_to

register = template.Library()


@register.simple_tag(takes_context=True)
def return_here(context, url):
    """`url` carrying the current page as its `return_to`, so its back link comes here."""
    return with_return_to(url, context["request"].get_full_path())


@register.simple_tag
def pass_return_to(url, return_to):
    """`url` carrying an existing `return_to` onward (e.g. from a detail page to its edit form)."""
    return with_return_to(url, return_to)
