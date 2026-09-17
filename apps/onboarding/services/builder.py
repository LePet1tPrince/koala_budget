"""
Turn questionnaire answers into a chart-of-accounts template.

Pure function of the answers -- no database access, no side effects -- so it can
be called to *preview* the chart of accounts during the review step and again to
apply it, with no risk the two disagree. The output is the dict shape
``apps.teams.services.template_engine.apply_template`` consumes.
"""

from ..coa_rules import BASE_GRANT, BASE_PAYEES, AccountSpec, Grant, GroupSpec
from ..questions import MULTI, QUESTION_CATALOG, Question


def _selected_values(question: Question, answers: dict) -> list[str]:
    """
    The option values chosen for one question, as a list regardless of shape.

    Tolerant of answers that do not match the catalog: an unknown value, a single
    string where a list was expected, or a missing key all yield nothing rather
    than raising. Answers can outlive the catalog that produced them.
    """
    raw = answers.get(question.id)
    if raw is None:
        return []

    values = raw if isinstance(raw, list) else [raw]
    valid = question.option_values
    return [v for v in values if isinstance(v, str) and v in valid]


def _selected_tokens(answers: dict) -> set[str]:
    """Every selected answer as a ``question_id:value`` token, for `Grant.requires`."""
    tokens = set()
    for question in QUESTION_CATALOG:
        for value in _selected_values(question, answers):
            tokens.add(f"{question.id}:{value}")
    return tokens


def collect_grants(answers: dict) -> list[Grant]:
    """
    Every grant the answers earn, base first, in catalog order.

    A grant whose ``requires`` is not satisfied is dropped -- that is how a
    dependent rule (a partner's salary account, say) stays quiet when the thing it
    depends on was not chosen.
    """
    tokens = _selected_tokens(answers)
    grants = [BASE_GRANT]

    for question in QUESTION_CATALOG:
        selected = set(_selected_values(question, answers))
        for option in question.options:
            if option.value not in selected:
                continue
            if any(token not in tokens for token in option.grant.requires):
                continue
            grants.append(option.grant)

    return grants


def build_template(answers: dict) -> dict:
    """
    Build the template for these answers.

    Deduplicates by name: several answers legitimately want the same account
    (a mortgage and a rental property both want Property Tax), and the first
    grant to claim a name wins. Groups referenced by a surviving account are
    always included, so an account can never be orphaned by a group that no
    answer happened to bring in.
    """
    groups: dict[str, GroupSpec] = {}
    accounts: dict[str, AccountSpec] = {}

    for grant in collect_grants(answers):
        for group in grant.groups:
            groups.setdefault(group.name, group)
        for account in grant.accounts:
            accounts.setdefault(account.name, account)

    # Safety net: a grant may list an account whose group it forgot to declare.
    # Rather than emitting a template that would KeyError in the engine, pull the
    # group in from the known set.
    known_groups = {g.name: g for g in _all_known_groups()}
    for account in accounts.values():
        if account.group not in groups and account.group in known_groups:
            groups[account.group] = known_groups[account.group]

    missing = sorted({a.group for a in accounts.values()} - set(groups))
    if missing:
        raise ValueError(f"template references undeclared account group(s): {', '.join(missing)}")

    ordered_groups = sorted(groups.values(), key=lambda g: (g.account_type, g.sort_order, g.name))
    ordered_accounts = sorted(accounts.values(), key=lambda a: (a.group, a.sort_order, a.name))

    return {
        "account_groups": [
            {
                "name": g.name,
                "type": g.account_type,
                "description": g.description,
                "is_system": g.is_system,
                "sort_order": g.sort_order,
            }
            for g in ordered_groups
        ],
        "accounts": [
            {
                "number": a.number,
                "name": a.name,
                "group": a.group,
                "has_feed": a.has_feed,
                "is_system": a.is_system,
                "sort_order": a.sort_order,
            }
            for a in ordered_accounts
        ],
        "payees": list(BASE_PAYEES),
    }


def _all_known_groups() -> list[GroupSpec]:
    """Every group any grant in the catalog can contribute, plus the base set."""
    groups = list(BASE_GRANT.groups)
    for question in QUESTION_CATALOG:
        for option in question.options:
            groups.extend(option.grant.groups)
    return groups


def unanswered_required(answers: dict) -> list[str]:
    """Ids of required questions with no usable answer yet."""
    missing = []
    for question in QUESTION_CATALOG:
        if not question.required:
            continue
        if question.kind == MULTI or question.options:
            if not _selected_values(question, answers):
                missing.append(question.id)
        elif not answers.get(question.id):
            missing.append(question.id)
    return missing
