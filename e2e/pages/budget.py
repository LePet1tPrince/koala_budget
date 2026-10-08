"""Page Object Models for the Budget and Goals pages (Django-template rendered)."""

from .base import BasePage


class BudgetPage(BasePage):
    def path(self, book) -> str:
        return f"{book.base_url}budget/"

    def goals_path(self, book) -> str:
        return f"{book.base_url}budget/goals/"

    def goal_create_path(self, book) -> str:
        return f"{book.base_url}budget/goals/new/"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto_budget(self, book):
        self.goto(self.path(book), wait_for="[data-testid='budget-table'], [data-testid='budget-empty-state']")

    def goto_goals(self, book, style: str | None = None):
        path = self.goals_path(book)
        if style:
            path = f"{path}?style={style}"
        self.goto(path, wait_for="[data-testid='goals-page']")

    def goto_goal_create(self, book):
        self.goto(self.goal_create_path(book), wait_for="[data-testid='goal-form']")

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
    # Hidden categories
    # ------------------------------------------------------------------

    def budget_row(self, name: str):
        return self.page.get_by_test_id("budget-row").filter(has_text=name)

    def hidden_row(self, name: str):
        return self.page.get_by_test_id("budget-hidden-row").filter(has_text=name)

    def hidden_toggle(self):
        return self.page.get_by_test_id("budget-hidden-toggle")

    def hide_category(self, name: str):
        self.budget_row(name).get_by_test_id("budget-hide-btn").click()
        self.hidden_row(name).wait_for(state="attached")

    def unhide_category(self, name: str):
        self.hidden_row(name).get_by_test_id("budget-unhide-btn").click()
        self.budget_row(name).wait_for()

    # ------------------------------------------------------------------
    # Goals queries
    # ------------------------------------------------------------------

    def get_goal_card_count(self) -> int:
        return self.page.locator("[data-testid='goal-card']").count()

    def has_goals_summary(self) -> bool:
        return self.page.locator("[data-testid='goals-summary']").is_visible()

    def has_goals_empty_state(self) -> bool:
        return self.page.locator("[data-testid='goals-empty-state']").is_visible()

    def goal_card(self, name: str):
        return self.page.locator("[data-testid='goal-card']", has_text=name)

    def goal_spent(self, name: str) -> str:
        return self.goal_card(name).locator("[data-testid='goal-spent']").inner_text().strip()

    def goal_left(self, name: str) -> str:
        return self.goal_card(name).locator("[data-testid='goal-left']").inner_text().strip()

    def goal_state(self, name: str) -> str:
        return self.goal_card(name).locator("[data-testid='goal-state']").get_attribute("data-state")

    def unassigned_pill_value(self) -> str:
        return self.page.locator("[data-testid='unassigned-pill'] [data-unassigned-pill-value]").inner_text().strip()

    def assign_available(self, goal_index: int = 0):
        self.page.locator("[data-testid='assign-available-btn']").nth(goal_index).click()

    def withdraw(self, goal_index: int = 0, amount: str | None = None):
        """Open a goal card's withdraw row and withdraw `amount` (or everything)."""
        card = self.page.locator("[data-testid='goal-card']").nth(goal_index)
        card.locator("[data-testid='withdraw-toggle']").click()
        if amount is None:
            card.locator("[data-testid='withdraw-all-btn']").click()
        else:
            card.locator("[data-withdraw-input]").fill(amount)
            card.locator("[data-testid='withdraw-btn']").click()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def click_new_goal(self):
        self.page.locator("[data-testid='new-goal-btn']").click()
        self.page.wait_for_selector("[data-testid='goal-form']")

    def create_goal(self, name: str, target_amount: str, book):
        """Navigate to the create form, fill it out, and submit."""
        self.goto_goal_create(book)
        self.page.locator("[name='name']").fill(name)
        self.page.locator("[name='target_amount']").fill(target_amount)
        self.page.locator("[data-testid='goal-submit-btn']").click()
        self.page.wait_for_url(f"**{book.base_url}budget/goals/**", timeout=10_000)

    # ------------------------------------------------------------------
    # Linked accounts (docs/goal-linked-accounts-plan.md)
    # ------------------------------------------------------------------

    def goal_link_row(self, account_name: str):
        return self.page.locator("[data-testid='goal-link-row']", has_text=account_name)

    def tick_link_account(self, account_name: str):
        self.goal_link_row(account_name).locator("[data-testid='goal-link-checkbox']").check()

    def link_preview(self):
        return self.page.locator("[data-testid='goal-link-preview']")

    def choose_outflow(self, value: str):
        self.page.locator(f"[data-testid='goal-outflow'] input[value='{value}']").check()

    def submit_goal_form(self):
        self.page.locator("[data-testid='goal-submit-btn']").click()

    def goal_card_links(self, name: str) -> str:
        return self.goal_card(name).locator("[data-testid='goal-card-links']").inner_text().strip()

    def goal_saved(self, name: str) -> str:
        return self.goal_card(name).locator("[data-num='allocated']").inner_text().strip()

    def goto_goal_detail(self, book, goal):
        self.goto(f"{book.base_url}budget/goals/{goal.pk}/", wait_for="[data-testid='goal-accounts']")

    def detail_links(self):
        return self.page.locator("[data-testid='goal-link']")

    def unlink_first(self):
        self.page.locator("[data-testid='goal-unlink-btn']").first.click()
        self.page.wait_for_load_state()

    def cancel_goal_form(self):
        self.page.locator("[data-testid='goal-cancel-btn']").click()

    # ------------------------------------------------------------------
    # The budget page's Goals section (docs/goal-plans-plan.md §6)
    # ------------------------------------------------------------------

    def goal_plan_row(self, name: str):
        return self.page.get_by_test_id("budget-goal-row").filter(has_text=name)

    def goal_plan_input(self, name: str):
        return self.goal_plan_row(name).get_by_test_id("goal-plan-input")

    def goal_plan_actual(self, name: str) -> str:
        return self.goal_plan_row(name).get_by_test_id("budget-goal-actual").inner_text().strip()

    def goal_held(self, name: str):
        """The "$X to move" line under a linked goal's Available (hidden when nothing waits)."""
        return self.goal_plan_row(name).get_by_test_id("goal-held")

    def wait_for_goal_save(self, name: str):
        """A goal row's save is done once its status dot settles (saved or idle, never saving)."""
        status = self.goal_plan_row(name).locator("[data-budget-status]")
        self.page.wait_for_function(
            "el => !el.classList.contains('is-saving')", arg=status.element_handle(), timeout=10_000
        )

    def set_goal_plan(self, name: str, amount: str):
        field = self.goal_plan_input(name)
        field.fill(amount)
        field.press("Enter")
        self.page.wait_for_timeout(200)
        self.wait_for_goal_save(name)

    def reset_goal_plan(self, name: str):
        self.goal_plan_row(name).get_by_test_id("goal-plan-reset").click()
        self.page.wait_for_timeout(200)
        self.wait_for_goal_save(name)
