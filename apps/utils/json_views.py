"""
Error handling for the DRF views a page calls with `fetch` (the generated client).

Used by the YNAB import and data import endpoints, whose long-running steps can
fail in ways no serializer anticipates.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

GENERIC_ERROR = "The server could not complete that step."


class UnexpectedErrorsAsJson:
    """
    An unexpected exception in a DRF view answers JSON, not Django's HTML error page.

    DRF already answers its own exceptions (validation, 404, permission) as
    JSON; anything else it re-raises, and the page calling it is left with an
    HTML 500 it cannot read. Mixed in before the DRF view class, this logs the
    exception with its traceback and answers `{"detail": message, "debug": ...}`
    with a 500 -- `debug` carrying the reason itself in DEBUG only, because a
    developer looking at the page is the person who can act on it.
    """

    unexpected_error_message = GENERIC_ERROR
    unexpected_error_label = "API request"

    def handle_exception(self, exc):
        from django.core.exceptions import PermissionDenied
        from django.http import Http404
        from rest_framework.exceptions import APIException
        from rest_framework.response import Response

        from apps.utils.errors import Refused

        if isinstance(exc, APIException | Http404 | PermissionDenied | Refused):
            return super().handle_exception(exc)
        logger.exception("%s failed: %s", self.unexpected_error_label, self.request.path)
        debug = f"{type(exc).__name__}: {exc}" if settings.DEBUG else ""
        return Response({"detail": str(self.unexpected_error_message), "debug": debug}, status=500)
