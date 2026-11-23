from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.utils.models import BaseModel

from .kinds import KIND_CHOICES


class EmailPreferences(BaseModel):
    """Which optional emails a person gets. A person without a row gets them all."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_preferences")
    bank_connection_alerts = models.BooleanField(
        _("Bank connection alerts"),
        default=True,
        help_text=_("When a linked bank needs you to sign in again, or its access is about to expire."),
    )
    budget_alerts = models.BooleanField(
        _("Overspending alerts"),
        default=True,
        help_text=_("A morning email when spending takes a budget category below zero this month."),
    )

    class Meta:
        verbose_name_plural = "email preferences"

    def __str__(self):
        return f"Email preferences for {self.user}"

    @classmethod
    def for_user(cls, user) -> "EmailPreferences":
        """The person's preferences, unsaved defaults when they never changed them."""
        try:
            return user.email_preferences
        except cls.DoesNotExist:
            return cls(user=user)


class SentEmail(BaseModel):
    """
    One email sent, under each key it covers. The unique key is what keeps an
    alert from going out twice: `services.send` records the keys first and skips
    the email when every one of them was already there.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_emails")
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    key = models.CharField(max_length=255, help_text="What the email was about, e.g. an item, a status and a day")
    book = models.ForeignKey("books.Book", null=True, blank=True, on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "kind", "key"], name="emails_sent_once_per_key")]
        indexes = [models.Index(fields=["kind", "created_at"])]

    def __str__(self):
        return f"{self.kind} to {self.user} ({self.key})"
