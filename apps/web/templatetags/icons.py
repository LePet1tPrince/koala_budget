"""Inline SVG icons (restyle plan Phase 6).

Replaces the Font Awesome CDN. The geometry comes from Lucide and lives in
`assets/icons/lucide.json`, with `assets/icons/aliases.json` mapping the old
Font Awesome names onto it — both files are read by this tag *and* by
`assets/javascript/common/Icon.jsx`, so templates and React draw from one
source rather than two that can drift.

Usage:

    {% load icons %}
    {% icon "home" %}
    {% icon "home" class="w-5 h-5 text-primary" %}

`name` accepts either a Lucide name or one of the Font Awesome aliases, so
call sites converted from the old font icons keep reading naturally.
"""

import json
from functools import lru_cache
from pathlib import Path

from django import template
from django.conf import settings
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

ICONS_DIR = Path(settings.BASE_DIR) / "assets" / "icons"

# Lucide draws on a 24x24 grid with a 2px stroke and no fill; `currentColor`
# makes an icon inherit the text colour it sits in, as the font icons did.
SVG_ATTRS = (
    'xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true"'
)

DEFAULT_CLASS = "inline-block w-4 h-4 shrink-0"


@lru_cache(maxsize=1)
def _load():
    geometry = json.loads((ICONS_DIR / "lucide.json").read_text())
    aliases = json.loads((ICONS_DIR / "aliases.json").read_text())
    return geometry, aliases


def render_icon(name, css_class=None):
    geometry, aliases = _load()
    key = aliases.get(name, name)
    body = geometry.get(key)
    if body is None:
        # A missing icon should be obvious in review, not silently blank, but it
        # must not take the page down either.
        if settings.DEBUG:
            raise template.TemplateSyntaxError(f"Unknown icon {name!r} (resolved to {key!r})")
        return ""
    return format_html(
        '<svg class="{}" {}>{}</svg>',
        css_class or DEFAULT_CLASS,
        mark_safe(SVG_ATTRS),  # noqa: S308 — a module constant, not user input
        mark_safe(body),  # noqa: S308 — generated from lucide-static at author time
    )


@register.simple_tag(name="icon")
def icon_tag(name, **kwargs):
    return render_icon(name, kwargs.get("class"))
