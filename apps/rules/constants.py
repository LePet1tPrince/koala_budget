"""
Every threshold the rules feature uses (docs/transaction-rules-plan.md §2). Nowhere else.
"""

from decimal import Decimal

# Trust graduation: consecutive unchanged confirmations before offering auto-post.
GRADUATE_STREAK = 5

# Demotion: an auto-post rule overridden this many times within its most recent
# auto-posted matches drops back to suggest.
DEMOTE_WINDOW = 10
DEMOTE_OVERRIDES = 2

# Anomaly guard: an auto-post match more than this multiple of the rule's median
# amount is held as a suggestion, once the rule has this many matches to judge by.
ANOMALY_MULTIPLE = Decimal("3")
ANOMALY_MIN_SAMPLES = 5

# Learned rules: a payee signature categorized this many times, this consistently.
LEARN_MIN_COUNT = 4
LEARN_MIN_CONSISTENCY = Decimal("0.9")
# Only books with a categorization this recent are scanned each night.
LEARN_ACTIVE_DAYS = 30

MAX_RULES_PER_BOOK = 200
MAX_CONDITIONS_PER_RULE = 10

# Create-from-action: a draft is offered only when it would cover this many transactions.
DRAFT_MIN_COVERAGE = 2

# Test / backtest bounds.
TEST_PENDING_ROWS = 50
TEST_DIFFER_ROWS = 20
BACKTEST_MONTHS = 24
