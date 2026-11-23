"""
Reading the questionnaire's answers, and the one thing an answer creates directly.

The client is not trusted to send a well-formed payload: what it posts is kept
only where the catalog recognises it, so an answer for a question that has since
been cut never sits in the database meaning nothing.
"""

from decimal import Decimal, InvalidOperation

from django.utils.dateparse import parse_date

from apps.budget.models import Goal

from ..questions import GOAL, QUESTION_CATALOG


def clean_answers(raw: dict) -> dict:
    """Keep only answers the catalog recognises, each in the shape its question takes."""
    cleaned = {}
    for question in QUESTION_CATALOG:
        if question.id not in raw:
            continue
        value = raw[question.id]

        if question.options:
            valid = question.option_values
            if isinstance(value, list):
                kept = [v for v in value if isinstance(v, str) and v in valid]
            elif isinstance(value, str) and value in valid:
                kept = [value]
            else:
                kept = []
            if kept:
                cleaned[question.id] = kept
        elif question.kind == GOAL:
            if goal := clean_goal(value):
                cleaned[question.id] = goal
        elif isinstance(value, str | int | float) and str(value).strip():
            cleaned[question.id] = value

    return cleaned


def clean_goal(value) -> dict | None:
    """
    A goal answer is a composite, and every field is optional.

    A blank name is how the user skips the question, so it yields nothing rather
    than a half-formed goal.
    """
    if not isinstance(value, dict):
        return None

    name = str(value.get("name") or "").strip()
    if not name:
        return None

    goal = {"name": name[:200]}

    try:
        amount = Decimal(str(value.get("target_amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        amount = None
    goal["target_amount"] = str(amount) if amount and amount > 0 else None

    target_date = str(value.get("target_date") or "").strip()
    goal["target_date"] = target_date or None

    return goal


def create_first_goal(book, answers: dict):
    """
    Create the goal the user named, so the Goals page is not empty on first visit.

    `Goal.save()` auto-creates the backing equity account in a non-system "Goals" group.
    """
    question = next((q for q in QUESTION_CATALOG if q.kind == GOAL), None)
    if question is None:
        return

    goal = answers.get(question.id)
    if not isinstance(goal, dict) or not goal.get("name"):
        return

    target_date = None
    if raw_date := goal.get("target_date"):
        target_date = parse_date(raw_date)

    Goal.objects.create(
        book=book,
        name=goal["name"],
        target_amount=Decimal(goal["target_amount"]) if goal.get("target_amount") else Decimal("0"),
        target_date=target_date,
    )
