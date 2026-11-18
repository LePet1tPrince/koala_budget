"""
Whether the guided task rail belongs on a book's pages.

Read by the `onboarding_rail` context processor and the nav-state API. Deliberately
cheap -- one query for the onboarding row: the rail fetches its own task state from
`api/tasks/` once it mounts, so the gates never run for a book with no rail.
"""

from ..models import OnboardingState


def shows_task_rail(book) -> bool:
    """True while `book`'s walkthrough is in its guided-tasks phase."""
    state = OnboardingState.objects.filter(book=book).only("phase").first()
    return state is not None and state.shows_tasks
