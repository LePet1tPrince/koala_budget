"""
Categorization rules, and the record of what filed a transaction automatically.

See `docs/categorization-rules-plan.md`. A rule says "a bank transaction that
looks like *this* is *that*"; a decision records that a provider (a rule today,
history or an AI later) filed one row, so the feed and the audit trail can say so.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.books.models import BaseBookModel

# Match kinds for the payee and description conditions. All of them compare text
# through `similar_transactions.normalize` / `signature_tokens` (see matching.py).
MATCH_ANY = ""
MATCH_EQUALS = "equals"
MATCH_CONTAINS = "contains"
MATCH_WORDS = "words"
MATCH_CHOICES = [
    (MATCH_ANY, _("Any")),
    (MATCH_EQUALS, _("is")),
    (MATCH_CONTAINS, _("contains")),
    (MATCH_WORDS, _("has the words")),
]

DIRECTION_ANY = "any"
DIRECTION_OUTFLOW = "outflow"
DIRECTION_INFLOW = "inflow"
DIRECTION_CHOICES = [
    (DIRECTION_ANY, _("Money in or out")),
    (DIRECTION_OUTFLOW, _("Money out")),
    (DIRECTION_INFLOW, _("Money in")),
]

MODE_AUTO = "auto"
MODE_SUGGEST = "suggest"
MODE_CHOICES = [
    (MODE_AUTO, _("Categorize automatically")),
    (MODE_SUGGEST, _("Suggest only")),
]

# Where an automatic categorization came from. Recorded on every decision and
# every audit event, so an AI-made decision is always identifiable.
SOURCE_RULE = "rule"
SOURCE_HISTORY = "history"
SOURCE_AI = "ai"
SOURCE_CHOICES = [
    (SOURCE_RULE, _("Rule")),
    (SOURCE_HISTORY, _("History")),
    (SOURCE_AI, _("AI")),
]


class CategorizationRuleQuerySet(models.QuerySet):
    def usable(self):
        """Enabled rules whose category can still be filed to (see `CategorizationRule.problem`)."""
        return self.filter(
            is_enabled=True,
            category__isnull=False,
            category__is_archived=False,
        ).exclude(category__account_group__account_type="budget")

    def in_order(self):
        return self.order_by("priority", "id")


class CategorizationRule(BaseBookModel):
    """
    One "transactions like this are that" rule.

    Conditions are ANDed and compared through the same normaliser as the history
    matcher; at least one of payee, description or amount must be set, so no rule
    matches everything. The highest-priority enabled rule that matches a row is
    *the* rule for it (first match wins).
    """

    name = models.CharField(max_length=200)
    priority = models.PositiveIntegerField(default=0, help_text=_("Lower runs first"))
    is_enabled = models.BooleanField(default=True)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_AUTO)

    # --- Conditions ---
    payee_match = models.CharField(max_length=10, choices=MATCH_CHOICES, default=MATCH_ANY, blank=True)
    payee_value = models.CharField(max_length=255, blank=True, default="")
    description_match = models.CharField(max_length=10, choices=MATCH_CHOICES, default=MATCH_ANY, blank=True)
    description_value = models.CharField(max_length=255, blank=True, default="")
    # On the magnitude: equal = exact, either may be blank for an open range.
    amount_min = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    amount_max = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, default=DIRECTION_ANY)
    # A rule scoped to an account that no longer exists means nothing: it goes too.
    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="categorization_rules_scoped",
        help_text=_("Only transactions in this bank feed account"),
    )

    # --- Actions (see actions.py; a future decision is a new column + one registered action) ---
    # SET_NULL, not CASCADE: deleting a category must not silently delete the
    # user's rule. A rule with no category is flagged and matches nothing.
    category = models.ForeignKey(
        "accounts.Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="categorization_rules",
    )
    set_payee = models.CharField(max_length=255, blank=True, default="", help_text=_("Rename the payee to"))
    set_description = models.CharField(max_length=255, blank=True, default="", help_text=_("Rename the description to"))

    # `is_enabled` is the one "off" switch; a second, archive state would compete with it.
    is_archived = None
    archived_at = None

    objects = CategorizationRuleQuerySet.as_manager()

    class Meta:
        ordering = ["priority", "id"]
        unique_together = ["book", "name"]
        verbose_name = "Categorization rule"
        verbose_name_plural = "Categorization rules"

    def __str__(self):
        return self.name

    @property
    def problem(self) -> str:
        """Why this rule cannot file anything right now, or "" when it can."""
        if self.category_id is None:
            return str(_("Its category was deleted. Choose a new one."))
        category = self.category
        if category.is_archived:
            return str(_("“%(name)s” is archived.") % {"name": category.name})
        if category.is_budget_bucket:
            return str(_("“%(name)s” is a budget account.") % {"name": category.name})
        return ""


class CategorizationDecision(BaseBookModel):
    """
    A bank row filed automatically -- by a rule today, by history or an AI later.

    Whether it still stands is derived, never maintained: only while the row is on
    `journal_entry` and its category is still `category` (`stands_for`). Filing the
    row again by hand needs no hook anywhere; the category stops agreeing and the
    feed's "Rule" badge goes.
    """

    bank_transaction = models.OneToOneField(
        "bank_feed.BankTransaction",
        on_delete=models.CASCADE,
        related_name="categorization_decision",
    )
    # Removing the category deletes the entry, and the decision with it.
    journal_entry = models.ForeignKey(
        "journal.JournalEntry",
        on_delete=models.CASCADE,
        related_name="categorization_decisions",
    )
    category = models.ForeignKey(
        "accounts.Account",
        on_delete=models.CASCADE,
        related_name="categorization_decisions",
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    provider = models.CharField(max_length=50, blank=True, default="")
    rule = models.ForeignKey(
        CategorizationRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decisions",
    )
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    reason = models.CharField(max_length=500, blank=True, default="")
    # What the bank sent, before a rule renamed it.
    original_payee = models.CharField(max_length=255, blank=True, default="")
    original_description = models.CharField(max_length=255, blank=True, default="")

    # A decision is a fact about the past; it is never archived.
    is_archived = None
    archived_at = None

    class Meta:
        verbose_name = "Categorization decision"
        verbose_name_plural = "Categorization decisions"
        indexes = [models.Index(fields=["rule"])]

    def __str__(self):
        return f"{self.source}: {self.bank_transaction_id} -> {self.category_id}"

    def stands_for(self, bank_transaction, category_id) -> bool:
        """True while `bank_transaction` is still filed the way this decision filed it."""
        return self.journal_entry_id == bank_transaction.journal_entry_id and self.category_id == category_id

    @property
    def label(self) -> str:
        """Short badge text: "Rule" / "AI" / "History"."""
        return str(dict(SOURCE_CHOICES).get(self.source, self.source))
