"""
Read-only questions about a rule, for the builder (plan §7.1, §9.1–9.3, §9.8).

* `test` -- for a draft rule (saved or not): the uncategorized rows it would win,
  how it would have done on the book's categorized history (backtest), and how
  it collides with the book's other rules (conflicts). Conflicts are empirical:
  counted over real rows, not proved from the conditions.
* `draft_from_transaction` -- the rule a categorization suggests, and whether it
  is worth offering ("Always categorize X as Y?").
* `explain` -- each part of a rule, passed or failed, for one transaction.

Nothing here writes.
"""

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalLine

from .. import constants
from ..models import Rule, RuleProposal
from . import actions, engine
from .apply import RuleSet, eligible, original_view
from .signatures import signature_for


def row_summary(tx, view=None):
    view = view or tx
    return {
        "id": tx.pk,
        "posted_date": tx.posted_date.isoformat(),
        "account_id": tx.account_id,
        "account_name": tx.account.name if tx.account_id else "",
        "payee": view.merchant_name or "",
        "description": view.description or "",
        "amount": str(tx.amount),
    }


def _single_categories(entry_ids, home_by_entry):
    """`{entry id: frozenset(category ids)}` -- every line but the row's own account's."""
    categories = {}
    for entry_id, account_id in JournalLine.objects.filter(journal_entry_id__in=entry_ids).values_list(
        "journal_entry_id", "account_id"
    ):
        if account_id != home_by_entry.get(entry_id):
            categories.setdefault(entry_id, set()).add(account_id)
    return {k: frozenset(v) for k, v in categories.items()}


def history_rows(book, months=constants.BACKTEST_MONTHS):
    """Categorized, counted, non-mirror rows from the backtest window, oldest decisions excluded."""
    since = timezone.localdate() - relativedelta(months=months)
    return (
        BankTransaction.objects.filter(
            book=book,
            journal_entry__isnull=False,
            is_void=False,
            is_transfer_mirror=False,
            posted_date__gte=since,
        )
        .select_related("account", "rule_match")
        .order_by("-posted_date", "-id")
    )


def _rule_categories(rule):
    if rule.action == Rule.ACTION_CATEGORY:
        return frozenset([rule.category_id])
    if rule.action == Rule.ACTION_SPLIT:
        return frozenset(actions.split_categories(rule))
    return None


def _same_action(a, b):
    return (
        a.action == b.action
        and _rule_categories(a) == _rule_categories(b)
        and (a.payee_name or "") == (b.payee_name or "")
        and (a.description or "") == (b.description or "")
    )


def test(book, draft, account_ids):
    """
    How `draft` (an unsaved or edited `Rule` instance, `account_ids` its accounts) would behave.

    Raises `engine.ConditionError` for a draft whose conditions cannot be read.
    """
    compiled_draft = engine.compile_rule(draft, account_ids=account_ids)
    others = [
        r for r in Rule.objects.filter(book=book, is_active=True).prefetch_related("accounts") if r.pk != draft.pk
    ]
    ruleset = RuleSet(book, rules=others)
    saved = ruleset.compiled
    together = engine.ordered([*saved, compiled_draft])
    draft_key = compiled_draft.sort_key

    shadowed_by, takes_from = {}, {}
    rules_by_id = {c.id: c.rule for c in saved}

    def tally(view):
        """(draft matches, draft wins); notes conflicts on the way."""
        if not engine.matches(view, compiled_draft):
            return False, False
        winner = engine.first_match(view, together)
        if winner is not compiled_draft:
            shadowed_by[winner.id] = shadowed_by.get(winner.id, 0) + 1
            return True, False
        loser = next((c for c in saved if c.sort_key > draft_key and engine.matches(view, c)), None)
        if loser is not None and not _same_action(loser.rule, draft):
            takes_from[loser.id] = takes_from.get(loser.id, 0) + 1
        return True, True

    pending_rows, pending_count = [], 0
    totals = {"matched": 0, "won": 0}

    def count(matched, won):
        totals["matched"] += matched
        totals["won"] += won

    for tx in eligible(book):
        view = original_view(tx)
        matched, won = tally(view)
        count(matched, won)
        if won:
            pending_count += 1
            if len(pending_rows) < constants.TEST_PENDING_ROWS:
                pending_rows.append(row_summary(tx, view))

    history = list(history_rows(book))
    homes = {tx.journal_entry_id: tx.account_id for tx in history}
    categories = _single_categories(list(homes), homes)
    wanted = _rule_categories(draft)
    accounts = actions.book_accounts(book)
    backtest = {"matched": 0, "agree": 0, "differ": 0, "differ_rows": []}
    for tx in history:
        view = original_view(tx)
        matched, won = tally(view)
        count(matched, won)
        if not matched:
            continue
        backtest["matched"] += 1
        actual = categories.get(tx.journal_entry_id, frozenset())
        if wanted is None or actual == wanted:
            backtest["agree"] += 1
            continue
        backtest["differ"] += 1
        if len(backtest["differ_rows"]) < constants.TEST_DIFFER_ROWS:
            row = row_summary(tx, view)
            row["category_names"] = sorted(accounts[a].name for a in actual if a in accounts)
            backtest["differ_rows"].append(row)

    def named(counts):
        return [
            {"rule_id": rule_id, "rule_name": rules_by_id[rule_id].name, "count": n}
            for rule_id, n in sorted(counts.items(), key=lambda kv: -kv[1])
        ]

    return {
        "pending": {"count": pending_count, "rows": pending_rows},
        "backtest": backtest,
        "conflicts": {
            "shadowed_by": named(shadowed_by),
            "takes_from": named(takes_from),
            "dead": totals["matched"] > 0 and totals["won"] == 0,
        },
    }


def draft_from_transaction(book, tx):
    """
    The rule `tx`'s categorization suggests, and whether to offer it.

    Returns `{"offer": bool, "reason": str, "rule": {...} | None, "coverage": n}`.
    """
    tx = BankTransaction.objects.select_related("account", "journal_entry").get(pk=tx.pk, book=book)
    signature = signature_for(original_view(tx))
    if signature is None:
        return {"offer": False, "reason": "nothing_distinctive", "rule": None, "coverage": 0}
    key, field, value = signature

    categories = _single_categories([tx.journal_entry_id], {tx.journal_entry_id: tx.account_id}).get(
        tx.journal_entry_id, frozenset()
    )
    if len(categories) != 1:
        return {"offer": False, "reason": "not_single_category", "rule": None, "coverage": 0}
    (category_id,) = categories
    accounts = actions.book_accounts(book)
    category = accounts.get(category_id)
    if category is None or category.is_budget_bucket:
        return {"offer": False, "reason": "not_single_category", "rule": None, "coverage": 0}

    direction = engine.DIRECTION_OUT if tx.amount > 0 else engine.DIRECTION_IN
    draft = {
        "name": _unique_name(book, f"{value.title()} → {category.name}"),
        "direction": direction,
        "accounts": [],
        "match": engine.MATCH_ALL,
        "conditions": [{"field": field, "op": engine.OP_CONTAINS, "value": value}],
        "action": Rule.ACTION_CATEGORY,
        "category": category.pk,
        "category_name": category.name,
        "mode": Rule.MODE_SUGGEST,
        "origin": Rule.ORIGIN_FROM_ACTION,
        "signature": key,
    }

    if RuleProposal.objects.filter(book=book, signature=key, status=RuleProposal.STATUS_DISMISSED).exists():
        return {"offer": False, "reason": "declined", "rule": draft, "coverage": 0}
    ruleset = RuleSet(book)
    if ruleset.first_match(original_view(tx)) is not None:
        return {"offer": False, "reason": "covered", "rule": draft, "coverage": 0}

    candidate = Rule(book=book, priority=0, **_rule_fields(draft))
    result = test(book, candidate, [])
    coverage = result["pending"]["count"] + result["backtest"]["matched"]
    offer = coverage >= constants.DRAFT_MIN_COVERAGE and not category.has_feed
    return {"offer": offer, "reason": "" if offer else "too_few", "rule": draft, "coverage": coverage}


def _rule_fields(data):
    return {
        "direction": data["direction"],
        "match": data["match"],
        "conditions": data["conditions"],
        "action": data["action"],
        "category_id": data.get("category"),
    }


def _unique_name(book, name):
    name = name[:100]
    taken = set(Rule.objects.filter(book=book, name__startswith=name[:90]).values_list("name", flat=True))
    if name not in taken:
        return name
    for n in range(2, 1000):
        candidate = f"{name[:94]} ({n})"
        if candidate not in taken:
            return candidate
    return f"{name[:80]} {timezone.now():%H%M%S}"


def explain(draft, account_ids, tx):
    """Per-part pass/fail of `draft` against `tx` as the bank reported it."""
    view = original_view(tx)
    result = engine.explain(view, engine.compile_rule(draft, account_ids=account_ids))
    result["transaction"] = row_summary(tx, view)
    return result


def insertion_index(book, conditions, account_ids, direction, exclude_id=None):
    """Where a new rule goes: above the first rule broader than it (plan §9.3)."""
    score = engine.specificity(conditions, account_ids, direction)
    rules = list(
        Rule.objects.filter(book=book).exclude(pk=exclude_id).prefetch_related("accounts").order_by("priority", "id")
    )
    for index, rule in enumerate(rules):
        if engine.specificity(rule.conditions, [a.pk for a in rule.accounts.all()], rule.direction) < score:
            return index, rules
    return len(rules), rules
