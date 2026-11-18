from django.test import Client, TestCase
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.validation import validate_schema


class ApiSchemaTestCase(TestCase):
    def test_schema_filters(self):
        c = Client()
        response = c.get("/api/schema/")
        response_yaml = response.content.decode("utf-8")
        self.assertFalse("/cms/" in response_yaml)


class SchemaGenerationTest(TestCase):
    """
    The schema is what `api-client/` is generated from, so an error in it is a
    broken client. Warnings (unresolvable type hints and the like) are allowed;
    errors are not.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        GENERATOR_STATS.reset()
        with GENERATOR_STATS.silence():
            cls.schema = SchemaGenerator().get_schema(request=None, public=True)
        cls.errors = dict(GENERATOR_STATS._error_cache)
        GENERATOR_STATS.reset()

    def test_no_errors(self):
        self.assertEqual(self.errors, {}, "drf-spectacular reported schema errors")

    def test_valid_openapi(self):
        validate_schema(self.schema)

    def test_platform_endpoints_are_typed(self):
        paths = self.schema["paths"]
        self.assertIn("/api/me/", paths)
        self.assertIn("/a/{team_slug}/{book_slug}/api/nav-state/", paths)
        me = paths["/api/me/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(me, {"$ref": "#/components/schemas/Me"})
        month = self.schema["components"]["schemas"]["NavUnassigned"]["properties"]["month"]
        self.assertEqual(month["pattern"], r"^[0-9]{4}-[0-9]{2}$")

    def test_session_token_scheme_is_documented(self):
        schemes = self.schema["components"]["securitySchemes"]
        self.assertEqual(schemes["XSessionTokenAuth"]["name"], "X-Session-Token")
        self.assertIn({"XSessionTokenAuth": []}, self.schema["paths"]["/api/me/"]["get"]["security"])
