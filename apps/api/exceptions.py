from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.views import set_rollback

from apps.utils.errors import Refused


def exception_handler(exc, context):
    """DRF's handler, plus a `Refused` answered as `{"error": message}`."""
    if isinstance(exc, Refused):
        set_rollback()
        return Response({"error": str(exc)}, status=exc.status_code)
    return drf_exception_handler(exc, context)
