"""
Category suggestions from similar transactions.

The same merchant is billed over and over, so how a book categorized a payee
before is the best available guess for how they want it categorized now. This
service looks back over the book's already-categorized bank transactions and,
for each uncategorized one, returns the categories that were used on
transactions that look like it — with a count, so the UI can say *why* it is
suggesting a category ("4 transactions with this payee were categorized as
Groceries") rather than presenting an unexplained guess.

Three tiers of "looks like it", strongest first:

  ``payee``        the merchant/payee name matches once punctuation and casing
                   are normalized away
  ``description``  the raw description matches after the same normalization
  ``similar``      the descriptions share most of their meaningful words —
                   this is what catches ``SQ *BLUE BOTTLE 4417`` against
                   ``SQ *BLUE BOTTLE 9920``, where the trailing terminal number
                   differs every time

Nothing here writes: it only suggests, and the user picks.
"""

import re

from apps.journal.models import counted_entries

from ..models import BankTransaction

MATCH_PAYEE = "payee"
MATCH_DESCRIPTION = "description"
MATCH_SIMILAR = "similar"

# Strongest first — a payee match beats a fuzzy description match.
MATCH_RANK = {MATCH_PAYEE: 0, MATCH_DESCRIPTION: 1, MATCH_SIMILAR: 2}

# How many recent categorized transactions to consider. Deep history adds little
# (a merchant categorized 40 times reads the same as one categorized 400 times)
# and this keeps the scan bounded for a long-lived book.
HISTORY_LIMIT = 2000

# How many suggestions to return per transaction. More than a few stops being a
# shortcut and becomes a second, worse category list.
DEFAULT_LIMIT = 3

# Share of meaningful words two descriptions must have in common to be called
# similar. 0.6 pairs "SQ *BLUE BOTTLE 4417" with "SQ *BLUE BOTTLE 9920" while
# keeping "SHELL GAS" apart from "SHELL OIL DIVIDEND".
SIMILARITY_THRESHOLD = 0.6

# A word this common across the book's history says nothing about which
# transaction is which, so it is not worth pulling candidates in on. The floor
# keeps the rule from swallowing a small history whole — in a 3-transaction
# history every word is in more than 20% of it.
COMMON_TOKEN_SHARE = 0.2
COMMON_TOKEN_FLOOR = 25

# Boilerplate banks staple onto descriptions; matching on these alone would pair
# every card purchase with every other one.
NOISE_TOKENS = frozenset(
    {
        "ach",
        "authorized",
        "card",
        "checkcard",
        "credit",
        "debit",
        "des",
        "eft",
        "electronic",
        "id",
        "indn",
        "payment",
        "pos",
        "ppd",
        "pmt",
        "purchase",
        "recurring",
        "ref",
        "transaction",
        "web",
        "xxxx",
    }
)

MIN_TOKEN_LENGTH = 3

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text):
    """Lowercase ``text`` and reduce every run of punctuation to a single space."""
    if not text:
        return ""
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def signature_tokens(text):
    """
    The meaningful words of ``text``, as a set.

    Digits are dropped wholesale: card fragments, terminal ids and order numbers
    are exactly the part of a description that differs between two transactions
    at the same merchant.
    """
    tokens = set()
    for token in normalize(text).split():
        if token.isdigit():
            continue
        if len(token) < MIN_TOKEN_LENGTH:
            continue
        if token in NOISE_TOKENS:
            continue
        tokens.add(token)
    return tokens


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class HistoryIndex:
    """
    The book's categorized transactions, indexed for lookup by payee, by
    description and by shared words.

    Built once and queried for many transactions, so scanning a whole
    categorize-mode queue costs a single pass over the history.
    """

    def __init__(self, records):
        self._records = records
        self._by_payee = {}
        self._by_description = {}
        self._by_token = {}

        for index, record in enumerate(records):
            if record["payee_key"]:
                self._by_payee.setdefault(record["payee_key"], []).append(index)
            if record["description_key"]:
                self._by_description.setdefault(record["description_key"], []).append(index)
            for token in record["tokens"]:
                self._by_token.setdefault(token, []).append(index)

        # Words that turn up all over the history are not distinguishing, and
        # pulling every record carrying one into the candidate set would make the
        # fuzzy pass scan the whole index for each transaction.
        ceiling = max(int(len(records) * COMMON_TOKEN_SHARE), COMMON_TOKEN_FLOOR)
        self._selective_tokens = {token for token, rows in self._by_token.items() if len(rows) <= ceiling}

    def __len__(self):
        return len(self._records)

    def matches(self, payee_key, description_key, tokens):
        """
        Return ``{history index: match tier}`` for every record that looks like
        the transaction described by the given keys, keeping the strongest tier
        when a record matches more than one way.
        """
        found = {}

        for index in self._by_payee.get(payee_key, ()) if payee_key else ():
            found[index] = MATCH_PAYEE

        for index in self._by_description.get(description_key, ()) if description_key else ():
            if index not in found:
                found[index] = MATCH_DESCRIPTION

        if tokens:
            candidates = set()
            for token in tokens & self._selective_tokens:
                candidates.update(self._by_token[token])
            for index in candidates:
                if index in found:
                    continue
                if _jaccard(tokens, self._records[index]["tokens"]) >= SIMILARITY_THRESHOLD:
                    found[index] = MATCH_SIMILAR

        return found

    def record(self, index):
        return self._records[index]


def build_history_index(book, limit=HISTORY_LIMIT):
    """
    Index the book's recent categorized bank transactions.

    Excluded, because none of them represents a decision the user made about a
    merchant: voided and archived transactions, and transfer mirror legs (the
    synthetic counterpart of a transfer, which shares its primary's journal
    entry and would count the same decision twice).
    """
    transactions = (
        BankTransaction.objects.filter(
            book=book,
            journal_entry__isnull=False,
            is_archived=False,
            is_transfer_mirror=False,
        )
        .filter(counted_entries("journal_entry__"))
        .select_related("account")
        .prefetch_related("journal_entry__lines__account")
        .order_by("-posted_date", "-created_at")[:limit]
    )

    records = []
    for tx in transactions:
        category = next(
            (
                line.account
                for line in tx.journal_entry.lines.all()
                if line.account_id != tx.account_id and not line.account.is_archived
            ),
            None,
        )
        if category is None:
            continue
        text = tx.merchant_name or tx.description or ""
        records.append(
            {
                "id": tx.id,
                "category_id": category.id,
                "category_name": category.name,
                "payee": tx.merchant_name or "",
                "payee_key": normalize(tx.merchant_name),
                "description_key": normalize(tx.description),
                "tokens": signature_tokens(text),
                "posted_date": tx.posted_date,
            }
        )
    return HistoryIndex(records)


def suggest_categories_for(transaction, index, limit=DEFAULT_LIMIT):
    """
    Rank the categories used on transactions similar to ``transaction``.

    Each suggestion is ``{category_id, category_name, count, match_type,
    payee}``, where ``count`` is how many similar transactions carried that
    category and ``match_type`` is the strongest tier any of them matched on —
    together, the sentence the UI puts under the suggestion. Ordered by tier,
    then by count, then by how recently the category was used that way.
    """
    payee_key = normalize(transaction.merchant_name)
    description_key = normalize(transaction.description)
    tokens = signature_tokens(transaction.merchant_name or transaction.description or "")

    matches = index.matches(payee_key, description_key, tokens)

    by_category = {}
    for history_index, match_type in matches.items():
        record = index.record(history_index)
        if record["id"] == transaction.id:
            continue  # an already-categorized transaction is not evidence about itself
        suggestion = by_category.get(record["category_id"])
        if suggestion is None:
            by_category[record["category_id"]] = {
                "category_id": record["category_id"],
                "category_name": record["category_name"],
                "count": 1,
                "match_type": match_type,
                "payee": record["payee"],
                "last_used": record["posted_date"],
            }
            continue
        suggestion["count"] += 1
        if MATCH_RANK[match_type] < MATCH_RANK[suggestion["match_type"]]:
            suggestion["match_type"] = match_type
            suggestion["payee"] = record["payee"]
        if record["posted_date"] > suggestion["last_used"]:
            suggestion["last_used"] = record["posted_date"]

    ranked = sorted(
        by_category.values(),
        key=lambda s: (MATCH_RANK[s["match_type"]], -s["count"], -s["last_used"].toordinal(), s["category_name"]),
    )
    for suggestion in ranked:
        suggestion.pop("last_used")
    return ranked[:limit]


def suggest_categories(book, transactions, limit=DEFAULT_LIMIT):
    """
    Suggest categories for several transactions at once.

    Returns ``{transaction id: [suggestion, ...]}``, omitting transactions with
    nothing to suggest. The history is indexed once for the whole batch.
    """
    transactions = list(transactions)
    if not transactions:
        return {}

    index = build_history_index(book)
    if not len(index):
        return {}

    results = {}
    for transaction in transactions:
        suggestions = suggest_categories_for(transaction, index, limit=limit)
        if suggestions:
            results[transaction.id] = suggestions
    return results
