"""The rules provider: the first rule (in priority order) that matches a row decides it."""

from django.utils.translation import gettext as _

from ..actions import decisions_from_rule
from ..matching import compile_rules, first_match
from ..models import MODE_AUTO, SOURCE_RULE, CategorizationRule
from .base import Suggestion


class RuleProvider:
    key = "rules"
    source = SOURCE_RULE
    can_auto_apply = True

    def compiled_rules(self, book):
        rules = CategorizationRule.objects.filter(book=book).usable().in_order().select_related("category")
        return compile_rules(rules)

    def suggest(self, context, rows):
        compiled = self.compiled_rules(context.book)
        if not compiled:
            return {}
        results = {}
        for row in rows:
            match = first_match(compiled, row)
            if match is None:
                continue
            results[row.id] = [suggestion_for(match.rule)]
        return results


def suggestion_for(rule) -> Suggestion:
    return Suggestion(
        category_id=rule.category_id,
        source=SOURCE_RULE,
        provider=RuleProvider.key,
        confidence=1.0,
        reason=_("Matches your rule “%(name)s”") % {"name": rule.name},
        auto=rule.mode == MODE_AUTO,
        category_name=rule.category.name if rule.category_id else "",
        rule_id=rule.id,
        rule_name=rule.name,
        match_type="rule",
        decisions=decisions_from_rule(rule),
    )
