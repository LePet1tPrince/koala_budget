from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.utils.json_views import GENERIC_ERROR, UnexpectedErrorsAsJson


class _View(UnexpectedErrorsAsJson, APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    error = None

    def get(self, request):
        if self.error:
            raise self.error
        return Response({"ok": True})


class UnexpectedErrorsAsJsonTest(SimpleTestCase):
    def call(self, error=None, **initkwargs):
        response = _View.as_view(error=error, **initkwargs)(RequestFactory().get("/somewhere/"))
        response.render()
        return response

    def test_a_normal_response_passes_through(self):
        self.assertEqual(self.call().data, {"ok": True})

    def test_drf_errors_keep_their_own_shape(self):
        response = self.call(ValidationError({"field": ["Bad."]}))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"field": ["Bad."]})

    @override_settings(DEBUG=False)
    def test_an_exception_becomes_a_json_500_without_debug(self):
        with self.assertLogs("apps.utils.json_views", level="ERROR"):
            response = self.call(RuntimeError("database on fire"))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data, {"detail": GENERIC_ERROR, "debug": ""})

    @override_settings(DEBUG=True)
    def test_debug_hands_the_reason_to_the_browser(self):
        with self.assertLogs("apps.utils.json_views", level="ERROR"):
            response = self.call(RuntimeError("database on fire"), unexpected_error_message="Custom message.")
        self.assertEqual(response.data, {"detail": "Custom message.", "debug": "RuntimeError: database on fire"})
