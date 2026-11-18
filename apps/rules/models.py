"""
Transaction rules: "when a feed transaction looks like this, categorize it like that".

A `Rule` is a set of conditions and an action. `services.apply.run` evaluates a
book's rules against new feed rows and records the outcome per row as a
`RuleMatch`: a suggestion the user confirms, or -- for an auto-post rule -- a
categorization already written. `RuleProposal` is a rule the book's history
suggests (`services.learning`), or a create-from-action offer the user declined.

Design and thresholds: docs/transaction-rules-plan.md.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.books.models import BaseBookModel


class Rule(BaseBookModel):
    MODE_SUGGEST = "suggest"
    MODE_AUTO_POST = "auto_post"
    MODE_CHOICES = [(MODE_SUGGEST, _("Suggest")), (MODE_AUTO_POST, _("Auto-post"))]

    DIRECTION_ANY = "any"
    DIRECTION_IN = "in"
    DIRECTION_OUT = "out"
    DIRECTION_CHOICES = [
        (DIRECTION_ANY, _("Money in or out")),
        (DIRECTION_IN, _("Money in")),
        (DIRECTION_OUT, _("Money out")),
    ]

    MATCH_ALL = "all"
    MATCH_ANY = "any"
    MATCH_CHOICES = [(MATCH_ALL, _("All conditions")), (MATCH_ANY, _("Any condition"))]

    # What the rule does on a match. Stored, not inferred from which fields are set:
    # a category rule whose category was deleted must read as broken, not as a
    # rename-only rule that quietly stopped categorizing.
    ACTION_CATEGORY = "category"
    ACTION_SPLIT = "split"
    ACTION_RENAME = "rename"
    ACTION_CHOICES = [(ACTION_CATEGORY, _("Categorize")), (ACTION_SPLIT, _("Split")), (ACTION_RENAME, _("Rename only"))]

    ORIGIN_MANUAL = "manual"
    ORIGIN_FROM_ACTION = "from_action"
    ORIGIN_LEARNED = "learned"
    ORIGIN_CHOICES = [
        (ORIGIN_MANUAL, _("Created by hand")),
        (ORIGIN_FROM_ACTION, _("Created from a categorization")),
        (ORIGIN_LEARNED, _("Proposed from history")),
    ]

    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=0, help_text="Lower wins")
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_SUGGEST)

    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES, default=DIRECTION_ANY)
    accounts = models.ManyToManyField(
        "accounts.Account",
        blank=True,
        related_name="+",
        help_text="Feed accounts the rule applies to; none = every account",
    )
    match = models.CharField(max_length=3, choices=MATCH_CHOICES, default=MATCH_ALL)
    conditions = models.JSONField(default=list, blank=True, help_text='[{"field", "op", "value"}]')

    action = models.CharField(max_length=10, choices=ACTION_CHOICES, default=ACTION_CATEGORY)
    category = models.ForeignKey(
        "accounts.Account",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    splits = models.JSONField(null=True, blank=True, help_text='[{"category": <id>, "percent": "<decimal>"}]')
    payee_name = models.CharField(max_length=200, blank=True, default="")
    description = models.CharField(max_length=255, blank=True, default="")

    origin = models.CharField(max_length=12, choices=ORIGIN_CHOICES, default=ORIGIN_MANUAL)
    times_applied = models.PositiveIntegerField(default=0)
    times_confirmed = models.PositiveIntegerField(default=0)
    times_overridden = models.PositiveIntegerField(default=0)
    confirm_streak = models.PositiveIntegerField(default=0)
    last_matched_at = models.DateTimeField(null=True, blank=True)
    graduation_declined_at = models.DateTimeField(null=True, blank=True)
    demoted_at = models.DateTimeField(null=True, blank=True)

    # A rule is switched off with `is_active`; the inherited archive flags would be a second way.
    is_archived = None
    archived_at = None

    class Meta:
        ordering = ["priority", "id"]
        unique_together = ["book", "name"]
        indexes = [models.Index(fields=["book", "priority", "id"], name="rule_book_priority")]

    def __str__(self):
        return self.name


class RuleMatch(BaseBookModel):
    """What a rule did, or offered to do, to one feed transaction."""

    STATUS_SUGGESTED = "suggested"
    STATUS_AUTO_POSTED = "auto_posted"
    STATUS_CONFIRMED = "confirmed"
    STATUS_OVERRIDDEN = "overridden"
    STATUS_DISMISSED = "dismissed"
    STATUS_CHOICES = [
        (STATUS_SUGGESTED, _("Suggested")),
        (STATUS_AUTO_POSTED, _("Auto-posted")),
        (STATUS_CONFIRMED, _("Confirmed")),
        (STATUS_OVERRIDDEN, _("Overridden")),
        (STATUS_DISMISSED, _("Dismissed")),
    ]
    # A row in one of these is settled: the engine never matches it again.
    SETTLED = (STATUS_CONFIRMED, STATUS_OVERRIDDEN, STATUS_DISMISSED)

    HELD_NONE = ""
    HELD_UNUSUAL_AMOUNT = "unusual_amount"
    HELD_TRANSFER_CANDIDATE = "transfer_candidate"
    HELD_CLOSED_PERIOD = "closed_period"
    HELD_REFUSED = "refused"
    HELD_CHOICES = [
        (HELD_NONE, _("Not held")),
        (HELD_UNUSUAL_AMOUNT, _("Unusual amount for this rule")),
        (HELD_TRANSFER_CANDIDATE, _("Might be a duplicate transfer")),
        (HELD_CLOSED_PERIOD, _("Dated in a closed period")),
        (HELD_REFUSED, _("Could not be posted automatically")),
    ]

    transaction = models.OneToOneField(
        "bank_feed.BankTransaction",
        on_delete=models.CASCADE,
        related_name="rule_match",
    )
    rule = models.ForeignKey(Rule, null=True, blank=True, on_delete=models.SET_NULL, related_name="matches")
    rule_name = models.CharField(max_length=100, help_text="The rule's name when it matched")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_SUGGESTED)
    held_reason = models.CharField(max_length=20, choices=HELD_CHOICES, blank=True, default=HELD_NONE)
    # What the rule offered or wrote, as of the match: the rule can change later,
    # and confirming must mean "what I was shown".
    category = models.ForeignKey("accounts.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    splits = models.JSONField(null=True, blank=True, help_text='[{"category": <id>, "amount": "<signed>"}]')
    payee_name = models.CharField(max_length=200, blank=True, default="")
    # True when the rule wrote the categorization itself; kept through a later override.
    was_auto_posted = models.BooleanField(default=False)
    before = models.JSONField(default=dict, blank=True, help_text="merchant_name and description before the rule")
    resolved_at = models.DateTimeField(null=True, blank=True)

    is_archived = None
    archived_at = None

    class Meta:
        indexes = [models.Index(fields=["book", "status"], name="rulematch_book_status")]

    def __str__(self):
        return f"{self.rule_name}: {self.status} ({self.transaction_id})"


class RuleProposal(BaseBookModel):
    """
    A rule the book's history argues for, or a "make this a rule?" the user declined.

    Keyed by signature (`services.signatures.signature_for`): once dismissed, that
    signature is never proposed or offered again.
    """

    FIELD_PAYEE = "payee"
    FIELD_DESCRIPTION = "description"
    FIELD_CHOICES = [(FIELD_PAYEE, _("Payee")), (FIELD_DESCRIPTION, _("Description"))]

    STATUS_OPEN = "open"
    STATUS_ACCEPTED = "accepted"
    STATUS_DISMISSED = "dismissed"
    STATUS_CHOICES = [(STATUS_OPEN, _("Open")), (STATUS_ACCEPTED, _("Accepted")), (STATUS_DISMISSED, _("Dismissed"))]

    signature = models.CharField(max_length=255)
    field = models.CharField(max_length=12, choices=FIELD_CHOICES)
    value = models.CharField(max_length=255, help_text="The condition text a rule from this proposal would match")
    direction = models.CharField(max_length=3, choices=Rule.DIRECTION_CHOICES, default=Rule.DIRECTION_ANY)
    category = models.ForeignKey("accounts.Account", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    evidence_count = models.PositiveIntegerField(default=0)
    consistency = models.DecimalField(max_digits=4, decimal_places=3, default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)

    is_archived = None
    archived_at = None

    class Meta:
        ordering = ["-evidence_count", "id"]
        unique_together = ["book", "signature"]

    def __str__(self):
        return f"{self.signature} -> {self.category_id} ({self.status})"
