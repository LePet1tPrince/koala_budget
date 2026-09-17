import json
import re
from pathlib import Path

from django.conf import settings
from django.template import Context, Template, TemplateSyntaxError
from django.test import TestCase, override_settings

from apps.web.templatetags.icons import ICONS_DIR, render_icon

REPO_ROOT = Path(settings.BASE_DIR)

TEMPLATE_CALL = re.compile(r'\{%\s*icon\s+"([a-z0-9-]+)"')
JSX_CALL = re.compile(r'<Icon\s+name="([a-z0-9-]+)"')
FONT_AWESOME = re.compile(r'class(?:Name)?="[^"]*\bfa fa-')


def render(source, **context):
    return Template("{% load icons %}" + source).render(Context(context))


def source_files():
    for root, patterns in (("templates", ("*.html",)), ("assets", ("*.jsx", "*.vue"))):
        for pattern in patterns:
            yield from (REPO_ROOT / root).rglob(pattern)


class IconTagTests(TestCase):
    def test_renders_inline_svg(self):
        result = render('{% icon "home" %}')

        self.assertIn("<svg", result)
        self.assertIn('viewBox="0 0 24 24"', result)
        self.assertIn('stroke="currentColor"', result)
        self.assertIn("inline-block w-4 h-4 shrink-0", result)

    def test_class_overrides_the_default(self):
        result = render('{% icon "home" class="w-5 h-5 text-primary" %}')

        self.assertIn('class="w-5 h-5 text-primary"', result)
        self.assertNotIn("w-4 h-4", result)

    def test_font_awesome_alias_resolves(self):
        """Call sites converted from the old font icons keep the name they read by."""
        self.assertEqual(render('{% icon "home" %}'), render('{% icon "house" %}'))

    def test_name_from_a_template_variable(self):
        result = render("{% icon name %}", name="check")

        self.assertIn("<svg", result)

    @override_settings(DEBUG=True)
    def test_unknown_icon_raises_in_debug(self):
        with self.assertRaises(TemplateSyntaxError):
            render_icon("no-such-icon")

    @override_settings(DEBUG=False)
    def test_unknown_icon_is_blank_in_production(self):
        """A typo should not take a page down in production."""
        self.assertEqual(render_icon("no-such-icon"), "")


class IconCatalogTests(TestCase):
    """The catalog is data, so a stale entry is a test failure rather than a blank icon."""

    @classmethod
    def setUpTestData(cls):
        cls.geometry = json.loads((ICONS_DIR / "lucide.json").read_text())
        cls.aliases = json.loads((ICONS_DIR / "aliases.json").read_text())

    def test_every_alias_points_at_a_real_icon(self):
        dangling = sorted(name for name, target in self.aliases.items() if target not in self.geometry)

        self.assertEqual(dangling, [])

    def test_every_name_used_in_the_source_resolves(self):
        names = set()
        for path in source_files():
            text = path.read_text()
            names |= set(TEMPLATE_CALL.findall(text)) | set(JSX_CALL.findall(text))

        self.assertTrue(names, "found no icon call sites — has the scan gone stale?")
        unresolved = sorted(n for n in names if self.aliases.get(n, n) not in self.geometry)

        self.assertEqual(unresolved, [])

    def test_no_font_awesome_markup_remains(self):
        """Phase 6 dropped the Font Awesome CDN, so such a class would render nothing."""
        offenders = sorted(str(p.relative_to(REPO_ROOT)) for p in source_files() if FONT_AWESOME.search(p.read_text()))

        self.assertEqual(offenders, [])
