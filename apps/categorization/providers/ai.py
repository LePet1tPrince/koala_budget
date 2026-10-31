"""
The AI categorization provider -- a stub, deliberately.

This is the class to implement (see `docs/categorization-rules-plan.md` §10,
"Adding an AI provider"). It is not in the default
`settings.CATEGORIZATION_PROVIDERS`; append
"apps.categorization.providers.ai.AIProvider" there once `suggest` does
something. Until then it returns nothing, so registering it early is harmless.

What `suggest` receives:
  context.book                  the set of books
  context.categories            pickable categories, as the pickers show them
                                (id, name, account_type, account_group_name,
                                is_goal, goal_left, is_hidden, institution_name …)
  context.allowed_category_ids  the ids a suggestion may name
  rows                          uncategorized BankTransactions: id, description,
                                merchant_name, amount (positive = money out),
                                posted_date, account

What it returns: `{row.id: [Suggestion(...), ...]}`, strongest first, with
`source=SOURCE_AI`, `provider=self.key`, a 0..1 `confidence` and a `reason`
the user will read. Leave `auto` False -- whether an AI suggestion may ever
file a row is `policy.may_auto_apply`'s call (off until a per-book setting
says otherwise), not the provider's.

Do not import from `apps.ai` / `apps.chat` here without checking where those
apps are headed; build the model client this needs alongside it.
"""

from ..models import SOURCE_AI


class AIProvider:
    key = "ai"
    source = SOURCE_AI
    can_auto_apply = True  # still gated by policy.book_allows_auto -- False by default

    def suggest(self, context, rows):
        return {}
