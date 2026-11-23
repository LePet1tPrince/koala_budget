from django import template

from apps.teams.roles import is_admin

register = template.Library()


@register.filter
def is_admin_of(user, team):
    return is_admin(user, team)
