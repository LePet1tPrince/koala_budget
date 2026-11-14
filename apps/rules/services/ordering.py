"""
Rule priorities: dense, 0 = tried first. Every change renumbers the whole book's
rules so two rules never share a position and "move up" always means something.
"""

from django.db import transaction

from ..models import Rule


def _write(ordered):
    changed = []
    for index, rule in enumerate(ordered):
        if rule.priority != index:
            rule.priority = index
            changed.append(rule)
    if changed:
        Rule.objects.bulk_update(changed, ["priority"])


@transaction.atomic
def renumber(book):
    _write(list(Rule.objects.filter(book=book).select_for_update().order_by("priority", "id")))


@transaction.atomic
def place(book, rule, index):
    """Move `rule` to position `index` (clamped), shifting the rest."""
    others = list(Rule.objects.filter(book=book).exclude(pk=rule.pk).select_for_update().order_by("priority", "id"))
    index = max(0, min(int(index), len(others)))
    others.insert(index, rule)
    _write(others)


@transaction.atomic
def reorder(book, ids):
    """The book's rules in the order `ids` gives; rules it leaves out follow in their current order."""
    rules = {r.pk: r for r in Rule.objects.filter(book=book).select_for_update().order_by("priority", "id")}
    first = [rules.pop(pk) for pk in dict.fromkeys(ids) if pk in rules]
    _write([*first, *rules.values()])
