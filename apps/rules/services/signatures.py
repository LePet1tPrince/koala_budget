"""
"Which merchant is this?" for rule drafts and learned rules.

One key per merchant, shared by create-from-action (`analysis.draft_from_transaction`)
and the nightly learner (`learning`), so declining one silences the other.
"""

from apps.bank_feed.services.similar_transactions import NOISE_TOKENS, normalize, signature_tokens

from ..models import RuleProposal


def _is_filler(token):
    return token.isdigit() or token in NOISE_TOKENS or len(token) < 2


def description_text(description):
    """
    The part of a description worth matching on: normalized, with the digit-only
    and boilerplate words trimmed from both ends ("POS PURCHASE SHELL OIL 4417" ->
    "shell oil"). Inner words stay, so the result is a substring of the original.
    """
    tokens = normalize(description).split()
    while tokens and _is_filler(tokens[0]):
        tokens.pop(0)
    while tokens and _is_filler(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


def signature_for(tx):
    """
    `(signature, field, value)` for `tx`, or None when it has nothing distinctive.

    `value` is the condition text a rule would match on; `signature` is the key
    proposals are stored under.
    """
    payee = normalize(tx.merchant_name or "")
    if payee:
        return f"{RuleProposal.FIELD_PAYEE}:{payee}"[:255], RuleProposal.FIELD_PAYEE, payee
    tokens = signature_tokens(tx.description)
    value = description_text(tx.description)
    if not tokens or not value:
        return None
    return (
        f"{RuleProposal.FIELD_DESCRIPTION}:{' '.join(sorted(tokens))}"[:255],
        RuleProposal.FIELD_DESCRIPTION,
        value,
    )
