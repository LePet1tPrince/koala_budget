from django import template

from apps.web.settings_sections import grouped_sections, sections_for

register = template.Library()


@register.simple_tag(takes_context=True)
def settings_sections(context):
    """The flat section list, for the hub's cards."""
    return sections_for(context["request"])


@register.simple_tag(takes_context=True)
def settings_section_groups(context):
    """The section list folded into headed groups, for the rail."""
    return grouped_sections(context["request"])
