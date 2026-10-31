"""`{% can_manage_rules_script %}`: tells a React page whether to offer "Create rule"."""

from django import template
from django.utils.html import json_script

from apps.teams.roles import is_admin

register = template.Library()


@register.simple_tag(takes_context=True)
def can_manage_rules_script(context):
    """`<script id="can-manage-rules">true|false</script>`, read by `categorization/rulesApi.js`."""
    request = context.get("request")
    team = getattr(request, "team", None) if request else None
    allowed = bool(team and request.user.is_authenticated and is_admin(request.user, team))
    return json_script(allowed, "can-manage-rules")
