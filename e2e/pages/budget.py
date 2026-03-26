"""Page Object Models for the Budget and Goals pages (Django-template rendered)."""

from .base import BasePage


class BudgetPage(BasePage):
    def path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/budget/"

    def goals_path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/budget/goals/"

    def goal_create_path(self, team_slug: str) -> str:
        return f"/a/{team_slug}/budget/goals/new/"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto_budget(self, team_slug: str):
        self.goto(self.path(team_slug), wait_for="[data-testid='budget-table'], [data-testid='budget-empty-state']")

    def goto_goals(self, team_slug: str):
        self.goto(self.goals_path(team_slug), wait_for="[data-testid='goals-table'], [data-testid='goals-summary']")

    def goto_goal_create(self, team_slug: str):
        self.goto(self.goal_create_path(team_slug), wait_for="[data-testid='goal-form']")

    # ------------------------------------------------------------------
    # Budget table queries
    # ------------------------------------------------------------------

    def has_budget_table(self) -> bool:
        return self.page.locator("[data-testid='budget-table']").is_visible()

    def is_budget_empty(self) -> bool:
        return self.page.locator("[data-testid='budget-empty-state']").is_visible()

    def get_budget_row_count(self) -> int:
        return self.page.locator("[data-testid='budget-row']").count()

    def has_grand_total(self) -> bool:
        return self.page.locator("[data-testid='budget-grand-total']").is_visible()

    # ------------------------------------------------------------------
    # Goals queries
    # ------------------------------------------------------------------

    def has_goals_table(self) -> bool:
        return self.page.locator("[data-testid='goals-table']").is_visible()

    def get_goal_row_count(self) -> int:
        return self.page.locator("[data-testid='goal-row']").count()

    def has_goals_summary(self) -> bool:
        return self.page.locator("[data-testid='goals-summary']").is_visible()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def click_new_goal(self):
        self.page.locator("[data-testid='new-goal-btn']").click()
        self.page.wait_for_selector("[data-testid='goal-form']")

    def create_goal(self, name: str, target_amount: str, team_slug: str):
        """Navigate to the create form, fill it out, and submit."""
        self.goto_goal_create(team_slug)
        self.page.locator("[name='name']").fill(name)
        self.page.locator("[name='target_amount']").fill(target_amount)
        self.page.locator("[data-testid='goal-submit-btn']").click()
        self.page.wait_for_url(f"**/a/{team_slug}/budget/goals/**", timeout=10_000)

    def cancel_goal_form(self):
        self.page.locator("[data-testid='goal-cancel-btn']").click()
