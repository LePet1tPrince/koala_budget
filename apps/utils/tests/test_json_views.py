import json

from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.utils.json_views import GENERIC_ERROR, json_body, json_errors


class JsonBodyTest(SimpleTestCase):
    def post(self, body: bytes):
        return RequestFactory().post("/", data=body, content_type="application/json")

    def test_an_object_is_returned(self):
        self.assertEqual(json_body(self.post(b'{"a": 1}')), {"a": 1})

    def test_empty_malformed_non_object_and_undecodable_bodies_read_as_empty(self):
        for body in (b"", b"{not json", b"[1, 2]", b'"text"', b"\xff\xfe"):
            with self.subTest(body=body):
                self.assertEqual(json_body(self.post(body)), {})


class JsonErrorsTest(SimpleTestCase):
    def request(self):
        return RequestFactory().get("/somewhere/")

    def test_a_normal_response_passes_through(self):
        view = json_errors()(lambda request: JsonResponse({"ok": True}))
        self.assertEqual(view(self.request()).status_code, 200)

    @override_settings(DEBUG=False)
    def test_an_exception_becomes_a_json_500_without_detail(self):
        def broken(request):
            raise RuntimeError("database on fire")

        with self.assertLogs("apps.utils.json_views", level="ERROR"):
            response = json_errors()(broken)(self.request())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(json.loads(response.content), {"error": GENERIC_ERROR, "detail": ""})

    @override_settings(DEBUG=True)
    def test_debug_hands_the_reason_to_the_browser(self):
        def broken(request):
            raise RuntimeError("database on fire")

        with self.assertLogs("apps.utils.json_views", level="ERROR"):
            response = json_errors("Custom message.", log_label="Thing")(broken)(self.request())
        self.assertEqual(
            json.loads(response.content), {"error": "Custom message.", "detail": "RuntimeError: database on fire"}
        )
