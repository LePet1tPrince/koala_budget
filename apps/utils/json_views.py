"""
Helpers for views that a page calls with `fetch` and that answer JSON.

Shared by the onboarding, monthly review, YNAB import and data import
endpoints, which each carried their own copy of these.
"""

import functools
import json
import logging

from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger(__name__)

GENERIC_ERROR = "The server could not complete that step."


def json_body(request) -> dict:
    """
    The request's JSON body as a dict; `{}` for an empty, malformed or non-object
    body. The client is not trusted to send a well-formed payload, so every
    caller validates the keys it reads anyway -- a bad body just reads as one
    with nothing in it.
    """
    try:
        body = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def json_errors(message: str = GENERIC_ERROR, *, log_label: str = "JSON request"):
    """
    Answer an unexpected exception with JSON, not Django's HTML error page.

    The page reads `error` off the body. An unhandled exception returns an HTML
    page instead, which leaves it nothing to show but "Something went wrong.".
    The exception is still logged with its traceback, so an error tracker sees
    it, and in DEBUG the reason itself goes to the browser as `detail`, because
    a developer looking at the page is the person who can act on it.
    """

    def decorator(view):
        @functools.wraps(view)
        def wrapped(request, *args, **kwargs):
            try:
                return view(request, *args, **kwargs)
            except Exception as error:  # noqa: BLE001 - the page must say something, whatever broke
                logger.exception("%s failed: %s", log_label, request.path)
                detail = f"{type(error).__name__}: {error}" if settings.DEBUG else ""
                return JsonResponse({"error": message, "detail": detail}, status=500)

        return wrapped

    return decorator
