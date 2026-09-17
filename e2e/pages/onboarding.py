"""
Page Object Models for the guided onboarding walkthrough.

Two surfaces, both React: the full-screen takeover (welcome → questionnaire →
chart-of-accounts review) and the task rail that follows it over the real app.
Both need Vite, so tests using these must depend on `requires_vite`.

Locators are by `data-testid` throughout. The question ids come from
`apps.onboarding.questions.QUESTION_CATALOG` — deliberately not hardcoded in a
list here, because the catalog is meant to be edited and a POM that enumerated
the questions would have to be updated in lockstep.
"""

from .base import BasePage


class OnboardingPage(BasePage):
    """The full-screen takeover."""

    def path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/onboarding/"

    def goto_onboarding(self, team_slug: str):
        self.goto(self.path(team_slug), wait_for="[data-testid='onboarding-takeover']")

    # ------------------------------------------------------------------
    # Welcome
    # ------------------------------------------------------------------

    def is_welcome_visible(self) -> bool:
        return self.page.locator("[data-testid='onboarding-welcome']").is_visible()

    def start(self):
        self.page.locator("[data-testid='onboarding-start']").click()
        self.page.wait_for_selector("[data-testid^='onboarding-question-']", timeout=10_000)

    def skip(self):
        self.page.locator("[data-testid='onboarding-skip']").first.click()

    # ------------------------------------------------------------------
    # Questionnaire
    # ------------------------------------------------------------------

    def current_question_id(self) -> str | None:
        """The id of the question on screen, or None if the review step is up."""
        card = self.page.locator("[data-testid^='onboarding-question-']").first
        if card.count() == 0:
            return None
        return (card.get_attribute("data-testid") or "").replace("onboarding-question-", "")

    def choose(self, option_value: str):
        self.page.locator(f"[data-testid='option-{option_value}']").click()

    def continue_disabled(self) -> bool:
        return self.page.locator("[data-testid='onboarding-continue']").is_disabled()

    def continue_label(self) -> str:
        return self.page.locator("[data-testid='onboarding-continue']").inner_text()

    def click_continue(self):
        self.page.locator("[data-testid='onboarding-continue']").click()

    def go_back(self):
        self.page.locator("[data-testid='onboarding-back']").click()

    def answer_all(self, answers: dict[str, list[str]]):
        """
        Walk the questionnaire, answering each question from `answers`.

        Driven by whatever question is on screen rather than a fixed sequence, so
        adding or cutting a catalog entry does not break this. A question with no
        entry in `answers` is left alone, which is fine for the optional ones.
        Stops when the review step appears.
        """
        for _ in range(30):  # generous bound; the catalog is nowhere near this long
            question_id = self.current_question_id()
            if question_id is None:
                return

            for option in answers.get(question_id, []):
                self.choose(option)

            self.click_continue()
            self.page.wait_for_timeout(450)

            if self.is_review_visible():
                return

        raise AssertionError("questionnaire did not reach the review step")

    # ------------------------------------------------------------------
    # Chart-of-accounts review
    # ------------------------------------------------------------------

    def is_review_visible(self) -> bool:
        review = self.page.locator("[data-testid='coa-review']")
        return review.count() > 0 and review.is_visible()

    def account_names(self) -> set[str]:
        chips = self.page.locator("[data-testid^='coa-chip-']")
        return {
            (chips.nth(i).get_attribute("data-testid") or "").replace("coa-chip-", "") for i in range(chips.count())
        }

    def remove_account(self, name: str):
        self.page.locator(f"[data-testid='coa-remove-{name}']").click()
        self.page.wait_for_timeout(700)  # the list redraws from the server

    def confirm_accounts(self, team_slug: str):
        self.page.locator("[data-testid='onboarding-continue']").click()
        self.page.wait_for_url(f"**/a/{team_slug}/", timeout=30_000, wait_until="domcontentloaded")


class TaskRailPage(BasePage):
    """The guided task rail, which rides along on every app page."""

    def wait_for_rail(self):
        self.page.wait_for_selector("[data-testid='task-rail']", timeout=20_000)
        # The rail fetches its own state after mounting.
        self.page.wait_for_selector("[data-testid='task-import']", timeout=10_000)

    def is_visible(self) -> bool:
        return self.page.locator("[data-testid='task-rail']").count() > 0

    def task_state(self, slug: str) -> str:
        return self.page.locator(f"[data-testid='task-{slug}']").get_attribute("data-state")

    def task_states(self) -> dict[str, str]:
        return {slug: self.task_state(slug) for slug in ("import", "categorize", "budget", "report", "net_worth")}

    def open_task(self, slug: str):
        self.page.locator(f"[data-testid='task-{slug}']").click()

    def dismiss(self):
        self.page.locator("[data-testid='task-rail-dismiss']").click()

    def is_finish_card_visible(self) -> bool:
        return self.page.locator("[data-testid='onboarding-finish']").count() > 0

    # ------------------------------------------------------------------
    # Opening balances (Task 5's dialog)
    # ------------------------------------------------------------------

    def wait_for_opening_balances(self):
        self.page.wait_for_selector("[data-testid='opening-balances']", timeout=15_000)

    def opening_balance_inputs(self) -> int:
        return self.page.locator("input[data-testid^='opening-']").count()

    def fill_opening_balance(self, account_id: int, amount: str):
        self.page.locator(f"[data-testid='opening-{account_id}']").fill(amount)

    def save_opening_balances(self):
        self.page.locator("[data-testid='opening-save']").click()

    def wait_for_reveal(self):
        self.page.wait_for_selector("[data-testid='net-worth-reveal']", timeout=15_000)

    def revealed_net_worth(self) -> str:
        """
        The revealed figure once it has stopped moving.

        It counts up from the previous net worth over ~700ms, so reading it the
        instant the reveal appears catches a number partway through the animation
        — which is exactly how this was first written, and it failed on a value
        mid-flight. Polls until two consecutive reads agree.
        """
        figure = self.page.locator("[data-testid='net-worth-figure']")
        previous = None
        for _ in range(30):
            current = figure.inner_text()
            if current == previous:
                return current
            previous = current
            self.page.wait_for_timeout(100)
        return previous or ""


class DashboardOnboardingPage(BasePage):
    """The dashboard's "Finish setting up" nudge."""

    def goto_dashboard(self, team_slug: str):
        self.goto(f"/a/{team_slug}/")

    def has_resume_card(self) -> bool:
        return self.page.locator("[data-testid='onboarding-resume']").count() > 0

    def has_legacy_checklist(self) -> bool:
        """The old three-step checklist, retired in favour of the task rail."""
        return self.page.locator("[data-testid='onboarding-checklist']").count() > 0

    def resume(self):
        self.page.locator("[data-testid='onboarding-resume'] button").click()
