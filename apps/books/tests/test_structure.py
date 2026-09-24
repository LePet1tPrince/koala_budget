"""
Structural checks that keep the move to books from quietly regressing
(docs/books-plan.md §9), in the style of `test_icons.py` / `test_schema.py`.
"""

import ast
import re
from pathlib import Path

from django.apps import apps
from django.test import SimpleTestCase

from apps.books.migration_utils import BOOK_MODELS
from apps.books.models import BaseBookModel
from apps.teams.models import BaseTeamModel

APPS_DIR = Path(__file__).resolve().parents[2]
BOOK_MODEL_NAMES = {apps.get_model(label, name).__name__ for label, name in BOOK_MODELS}


def project_models():
    return [m for m in apps.get_models() if m.__module__.startswith("apps.")]


class BookModelStructureTest(SimpleTestCase):
    def test_every_book_model_is_listed(self):
        """`BOOK_MODELS` drives the migrations' backfill and the isolation snapshots."""
        concrete = {m._meta.label_lower for m in project_models() if issubclass(m, BaseBookModel)}
        self.assertEqual(concrete, {f"{label}.{name}" for label, name in BOOK_MODELS})

    def test_no_book_model_keeps_a_team_column(self):
        for model in project_models():
            if issubclass(model, BaseBookModel):
                with self.subTest(model=model._meta.label):
                    self.assertNotIn("team", {f.name for f in model._meta.get_fields()})

    def test_only_the_demo_is_still_team_scoped(self):
        team_models = {m._meta.label for m in project_models() if issubclass(m, BaseTeamModel)}
        self.assertEqual(team_models, {"teams_example.Player"})


class TeamFilterScanTest(SimpleTestCase):
    """
    A `team=` lookup against a book model is a query the sweep missed. The model
    no longer has the column, so it would fail loudly at runtime -- this finds it
    before anything runs.
    """

    LOOKUP = re.compile(r"\bteam(_id)?(__\w+)?$")

    def call_root(self, func):
        node = func
        while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
            node = node.func if isinstance(node, ast.Call) else node.value
        return node.id if isinstance(node, ast.Name) else None

    def test_no_source_filters_a_book_model_by_team(self):
        offenders = []
        for path in APPS_DIR.rglob("*.py"):
            # Migrations, and the test of them, use pre-books historical models.
            if "migrations" in path.parts or path.name == "test_migrations.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or self.call_root(node.func) not in BOOK_MODEL_NAMES:
                    continue
                for keyword in node.keywords:
                    if keyword.arg and self.LOOKUP.match(keyword.arg):
                        offenders.append(f"{path.relative_to(APPS_DIR.parent)}:{node.lineno} {keyword.arg}=")
        self.assertEqual(offenders, [])
