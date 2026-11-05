"""
A stand-in AI provider for tests -- and the pattern to copy when testing a real one.

Register it with `override_settings(CATEGORIZATION_PROVIDERS=[*DEFAULT_PROVIDERS,
"apps.categorization.tests.doubles.FakeAIProvider"])`; set `FakeAIProvider.answers`
to `{row_id: [(category_id, confidence), ...]}` and read back `FakeAIProvider.calls`.
"""

from apps.categorization.models import SOURCE_AI
from apps.categorization.providers.base import Suggestion

AI_PATH = "apps.categorization.tests.doubles.FakeAIProvider"


class FakeAIProvider:
    key = "ai"
    source = SOURCE_AI
    can_auto_apply = True

    answers = {}
    calls = []

    @classmethod
    def reset(cls, answers=None):
        cls.answers = dict(answers or {})
        cls.calls = []

    def suggest(self, context, rows):
        rows = list(rows)
        FakeAIProvider.calls.append({"book": context.book, "row_ids": [row.id for row in rows]})
        return {
            row.id: [
                Suggestion(
                    category_id=category_id,
                    source=self.source,
                    provider=self.key,
                    confidence=confidence,
                    reason="The model thinks so",
                    match_type="ai",
                )
                for category_id, confidence in FakeAIProvider.answers[row.id]
            ]
            for row in rows
            if row.id in FakeAIProvider.answers
        }


class BrokenProvider:
    key = "broken"
    source = SOURCE_AI
    can_auto_apply = False

    def suggest(self, context, rows):
        raise RuntimeError("model timed out")
