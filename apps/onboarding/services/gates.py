"""
Which guided tasks are open to a team, and why the closed ones are closed.

Computed server-side and handed to the client, so the UI renders what the server
says rather than deciding for itself. The gates are real: `api/opening-balances/`
refuses a team with no journal entries whatever the UI shows.

The two gating facts are deliberately different:

* **A bank transaction** means a file was imported. It unlocks categorizing and
  budgeting -- both need something to work on, neither needs it categorized.
* **A journal entry** means something was actually categorized. Only that moves a
  balance, so the report and net-worth steps wait for it. Gating them on the
  import alone would walk the user to an empty report and a flat line at the
  exact moment the walkthrough is meant to pay off.
"""

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _

# Task states.
LOCKED = "locked"
AVAILABLE = "available"
DONE = "done"

# What a task waits for.
NEEDS_NOTHING = "nothing"
NEEDS_TRANSACTIONS = "transactions"
NEEDS_ENTRIES = "entries"

GATE_REASONS = {
    NEEDS_TRANSACTIONS: _("Import some transactions first."),
    NEEDS_ENTRIES: _("Categorize a few transactions first — until then there's nothing to show."),
}


@dataclass(frozen=True)
class Task:
    slug: str
    label: str
    needs: str
    # True when completion is observable in the data; False when the task is
    # "go and look at this", which only the client can report.
    auto_detected: bool


TASKS: tuple[Task, ...] = (
    Task("import", _("Import your transactions"), NEEDS_NOTHING, auto_detected=True),
    Task("categorize", _("Categorize them"), NEEDS_TRANSACTIONS, auto_detected=True),
    Task("budget", _("Set a budget"), NEEDS_TRANSACTIONS, auto_detected=True),
    Task("report", _("See where the money went"), NEEDS_ENTRIES, auto_detected=False),
    Task("net_worth", _("Watch your net worth move"), NEEDS_ENTRIES, auto_detected=False),
)


@dataclass(frozen=True)
class TeamFacts:
    """The facts the gates depend on, fetched once rather than per task."""

    has_transactions: bool
    has_entries: bool
    has_budget: bool


def team_facts(team) -> TeamFacts:
    from apps.bank_feed.models import BankTransaction
    from apps.budget.models import Budget
    from apps.journal.models import JournalEntry

    return TeamFacts(
        has_transactions=BankTransaction.objects.filter(team=team).exists(),
        # A voided entry is excluded everywhere else in the app, so it must not
        # count as "you have categorized something" here either.
        has_entries=JournalEntry.objects.filter(team=team).exclude(status=JournalEntry.STATUS_VOID).exists(),
        has_budget=Budget.objects.filter(team=team).exists(),
    )


def _is_satisfied(needs: str, facts: TeamFacts) -> bool:
    if needs == NEEDS_TRANSACTIONS:
        return facts.has_transactions
    if needs == NEEDS_ENTRIES:
        return facts.has_entries
    return True


def _is_done(task: Task, facts: TeamFacts, tasks_done: list[str]) -> bool:
    # A task the user has been credited with stays done, even if the data that
    # proved it is later deleted -- being sent back through a step you finished
    # is worse than a checklist that is slightly out of date.
    if task.slug in tasks_done:
        return True
    if not task.auto_detected:
        return False
    return {
        "import": facts.has_transactions,
        "categorize": facts.has_entries,
        "budget": facts.has_budget,
    }.get(task.slug, False)


def task_state(team, tasks_done: list[str] | None = None) -> list[dict]:
    """
    Every guided task with its state, in order, plus the reason for any lock.
    """
    facts = team_facts(team)
    done = list(tasks_done or [])

    states = []
    for task in TASKS:
        if _is_done(task, facts, done):
            state = DONE
        elif _is_satisfied(task.needs, facts):
            state = AVAILABLE
        else:
            state = LOCKED

        states.append(
            {
                "slug": task.slug,
                "label": str(task.label),
                "state": state,
                "reason": str(GATE_REASONS[task.needs]) if state == LOCKED else "",
            }
        )
    return states


def can_set_opening_balances(team) -> bool:
    """
    Opening balances wait for real categorized activity.

    Enforced by the endpoint, not only hidden in the UI -- see the module
    docstring.
    """
    return team_facts(team).has_entries
