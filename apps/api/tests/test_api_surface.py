"""
The API-first rule, enforced (`docs/api-first-migration-plan.md`, WP9).

Every URL the app serves is one of:

* an HTML page, a file download or a plain no-JS form post (redirects) -- a
  plain Django view that never answers JSON; or
* a DRF view (`APIView` / `ViewSet` / `@api_view`) that appears in the OpenAPI
  schema, so `api-client/` -- the one contract the web app and the phone app
  share -- has a typed method for it.

A plain Django view that answers JSON is the thing this migration removed: it is
invisible to the schema, so the phone client has no method for it and nothing
types its payload. These tests walk the whole URLconf and fail with the list of
offenders. A legitimate exception goes in one of the allowlists below, with the
reason.

What "answers JSON" means for a plain view is read from its source (the view
function or class, through its decorators): `JsonResponse`, `json.dumps(` or an
`application/json` content type. `NoJsonResponseOutsideDrfTest` backs that up
module-wide, so a helper that builds the response elsewhere is caught too.
"""

import contextlib
import inspect
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import URLPattern, URLResolver, get_resolver
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator

JSON_MARKERS = ("JsonResponse", "json.dumps(", "application/json")

# Plain (non-DRF) views of ours that may answer JSON, by URL name.
NON_DRF_JSON_ALLOWED = {
    # Plaid's server-to-server webhook: global (Plaid can't know team or book
    # slugs), authenticated by Plaid's signed JWT rather than a user, and never
    # called by a client, so it has no place in the client's schema.
    "plaid_webhook": "Plaid webhook",
    # django-health-check's view: JSON for `Accept: application/json` monitors.
    "web:health_check": "health check",
}

# DRF views that are deliberately not in the schema, by view class path.
DRF_NOT_IN_SCHEMA_ALLOWED = {
    # A `DefaultRouter`'s browsable index of its routes (`api-root`): a listing of
    # links, not data; DRF itself excludes it from schemas.
    "rest_framework.routers.APIRootView": "router index",
    # The schema views themselves.
    "drf_spectacular.views.SpectacularAPIView": "the schema",
    "drf_spectacular.views.SpectacularSwaggerView": "schema UI",
    "drf_spectacular.views.SpectacularRedocView": "schema UI",
}

# Views from other packages, by module prefix. None of them is ours to put in
# the schema; a new third-party include fails until it is classified here.
THIRD_PARTY_ALLOWED = {
    "django.contrib.admin": "Django admin (staff HTML); model admins are matched by the `admin:` namespace",
    "django.contrib.admindocs": "admin docs (staff HTML)",
    "django.contrib.sitemaps": "sitemap.xml",
    "django.views.generic.base": "RedirectView",
    "django.views.i18n": "set_language form post and the JS translation catalog",
    "django.views.static": "media files in DEBUG",
    "django_browser_reload": "dev-only live reload",
    "debug_toolbar": "dev-only debug toolbar",
    # allauth's account pages are HTML; its headless JSON API (`/_allauth/`) has
    # its own OpenAPI spec and client contract (allauth's, not ours).
    "allauth": "allauth account pages and headless API",
    # Stripe's server-to-server webhook (dj-stripe), verified by Stripe's signature.
    "djstripe": "Stripe webhook",
    "hijack": "staff impersonation form posts",
}


def _walk(patterns, prefix="", namespace=""):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            inner = f"{namespace}{pattern.namespace}:" if pattern.namespace else namespace
            yield from _walk(pattern.url_patterns, prefix + str(pattern.pattern), inner)
        elif isinstance(pattern, URLPattern):
            name = f"{namespace}{pattern.name}" if pattern.name else None
            yield prefix + str(pattern.pattern), name, pattern.callback


def _is_drf(callback):
    from rest_framework.views import APIView

    cls = getattr(callback, "cls", None)
    return isinstance(cls, type) and issubclass(cls, APIView)


def _view_target(callback):
    """The view function or class behind `callback`, through its decorators."""
    seen = set()
    target = callback
    while id(target) not in seen:
        seen.add(id(target))
        if getattr(target, "view_class", None) is not None:
            return target.view_class
        for attr in ("__wrapped__", "f", "func", "view_func"):
            inner = getattr(target, attr, None)
            if callable(inner):
                target = inner
                break
        else:
            return target
    return target


def _module(target):
    return getattr(target, "__module__", None) or type(target).__module__


def _qualname(target):
    return f"{_module(target)}.{getattr(target, '__qualname__', type(target).__qualname__)}"


def _own_source(target):
    """The source of the view, and of its own (app) base classes for a CBV."""
    parts = []
    members = inspect.getmro(target) if isinstance(target, type) else [target]
    for member in members:
        if not _module(member).startswith("apps."):
            continue
        with contextlib.suppress(OSError, TypeError):
            parts.append(inspect.getsource(member))
    return "\n".join(parts)


def _label(route, name, target):
    return f"{route}  [{name or 'unnamed'}]  {_qualname(target)}"


class ApiSurfaceTest(SimpleTestCase):
    """Every view answering JSON is DRF and in the schema."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.urls = [
            (route, name, callback, _view_target(callback))
            for route, name, callback in _walk(get_resolver().url_patterns)
        ]
        generator = SchemaGenerator()
        GENERATOR_STATS.reset()
        with GENERATOR_STATS.silence():
            cls.schema = generator.get_schema(request=None, public=True)
            # (path, method, view) as the generator saw them, path-coerced the
            # same way as the schema's keys.
            cls.endpoints = generator._get_paths_and_endpoints()
        GENERATOR_STATS.reset()

    def test_the_walk_sees_the_app(self):
        names = {name for _route, name, _cb, _target in self.urls}
        for expected in ("web_book:home", "journal:journal-entry-list", "api:me", "plaid_webhook"):
            self.assertIn(expected, names)

    def test_no_plain_view_answers_json(self):
        offenders = []
        for route, name, callback, target in self.urls:
            if _is_drf(callback) or not _module(target).startswith("apps."):
                continue
            if name in NON_DRF_JSON_ALLOWED:
                continue
            source = _own_source(target)
            if any(marker in source for marker in JSON_MARKERS):
                offenders.append(_label(route, name, target))
        self.assertEqual(
            offenders,
            [],
            "These plain Django views answer JSON. Make each a DRF view with serializers "
            "(`docs/api-first-migration-plan.md`), or allowlist it with the reason:\n" + "\n".join(offenders),
        )

    def test_every_drf_view_is_in_the_schema(self):
        enumerated = {view.__class__ for _path, _regex, _method, view in self.endpoints}
        offenders = []
        for route, name, callback, _target in self.urls:
            if not _is_drf(callback) or "format" in route:  # a router's `.json` twin of a route
                continue
            if _qualname(callback.cls) in DRF_NOT_IN_SCHEMA_ALLOWED:
                continue
            if callback.cls not in enumerated:
                offenders.append(_label(route, name, callback.cls) + "  (not enumerated: `schema = None`?)")
        paths = self.schema["paths"]
        for path, _regex, method, view in self.endpoints:
            if _qualname(view.__class__) in DRF_NOT_IN_SCHEMA_ALLOWED:
                continue
            if method.lower() not in paths.get(path, {}):
                offenders.append(f"{method} {path}  {_qualname(view.__class__)}  (excluded from the schema?)")
        self.assertEqual(
            offenders,
            [],
            "These DRF views are missing from the OpenAPI schema, so the generated client has no "
            "method for them. Document them (`@extend_schema`), or allowlist with the reason:\n" + "\n".join(offenders),
        )

    def test_third_party_views_are_classified(self):
        unknown = sorted(
            {
                _label(route, name, target)
                for route, name, callback, target in self.urls
                if not _module(target).startswith("apps.")
                and not _is_drf(callback)
                # The admin site: staff HTML, whichever package registered the model admin.
                and not (name or "").startswith("admin:")
                and not any(_module(target).startswith(prefix) for prefix in THIRD_PARTY_ALLOWED)
            }
        )
        self.assertEqual(
            unknown,
            [],
            "Views from another package, unclassified. If one answers JSON to a client, wrap it in a "
            "DRF view of ours; otherwise add its module to THIRD_PARTY_ALLOWED with the reason:\n" + "\n".join(unknown),
        )

    def test_book_and_team_drf_urls_are_in_the_schema(self):
        # The headline rule, stated over the URLs it is about: every DRF route under
        # `/a/{team}/...` (team- and book-level) has a path in the schema.
        enumerated_regexes = {regex for _path, regex, _method, _view in self.endpoints}
        missing = [
            _label(route, name, callback.cls)
            for route, name, callback, _target in self.urls
            if route.startswith("a/")
            and _is_drf(callback)
            and "format" not in route
            and _qualname(callback.cls) not in DRF_NOT_IN_SCHEMA_ALLOWED
            and route not in enumerated_regexes
        ]
        self.assertEqual(missing, [], "\n".join(missing))
        self.assertGreater(len([p for p in self.schema["paths"] if p.startswith("/a/{team_slug}/")]), 100)


class TemplateDataPropsTest(SimpleTestCase):
    """
    Templates hand pages configuration, never data: a page loads its data through
    `api-client`, so the phone app can load the same thing. `json_script` may carry
    only the config ids below (anything else is a payload the API should serve).
    """

    CONFIG_IDS = {
        "book-base": "`/a/{team}/{book}/`, the root every book URL and api-client call is built from",
        "team-id": "the team a team page asks the API for",
        "api-urls": "page-link URL templates (teams pages), not data",
        "server-url": "the site's origin, for building invitation links",
    }
    # (template, id) pairs allowed to carry data, with the reason.
    DATA_ALLOWED = {
        # The superuser-only signups dashboard (`apps.dashboard`): an internal staff
        # page outside the user app (no team, no book), with no phone counterpart.
        ("dashboard/user_dashboard.html", "signup-data"): "staff-only signups chart",
    }

    JSON_SCRIPT = re.compile(r"json_script(?::\s*(?P<quote>['\"])(?P<id>[^'\"]*)(?P=quote))?")

    def test_json_script_carries_only_config(self):
        root = Path(settings.BASE_DIR) / "templates"
        offenders = []
        for path in sorted(root.rglob("*.html")):
            relative = path.relative_to(root).as_posix()
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                for match in self.JSON_SCRIPT.finditer(line):
                    element_id = match.group("id")
                    if element_id in self.CONFIG_IDS or (relative, element_id) in self.DATA_ALLOWED:
                        continue
                    offenders.append(f"{relative}:{lineno}  {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "These templates pass data via `json_script`. Serve it from a DRF endpoint and load it "
            "through api-client (with a loading state), or, if it is pure config, add the id to "
            "CONFIG_IDS with the reason:\n" + "\n".join(offenders),
        )

    def test_the_scan_finds_json_scripts(self):
        root = Path(settings.BASE_DIR) / "templates"
        found = sum(len(self.JSON_SCRIPT.findall(p.read_text())) for p in root.rglob("*.html"))
        self.assertGreater(found, 10)


class NoJsonResponseOutsideDrfTest(SimpleTestCase):
    """No app module builds a `JsonResponse` except the allowlisted ones."""

    ALLOWED = {
        "apps/plaid/views.py": "the Plaid webhook (see NON_DRF_JSON_ALLOWED)",
    }

    def test_no_json_response(self):
        root = Path(settings.BASE_DIR)
        offenders = []
        for path in sorted((root / "apps").rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if "/tests/" in relative or path.name.startswith("test") or "/migrations/" in relative:
                continue
            if relative in self.ALLOWED:
                continue
            if re.search(r"\bJsonResponse\b", path.read_text()):
                offenders.append(relative)
        self.assertEqual(
            offenders,
            [],
            "These modules use `JsonResponse`; answer JSON from a DRF view instead:\n" + "\n".join(offenders),
        )
