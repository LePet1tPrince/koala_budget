"""
The emails Koala Budget sends on its own (not the sign-in mail allauth sends).

Each kind names its templates (`templates/emails/<template>.html`, `.txt` and
`_subject.txt`) and the `EmailPreferences` field that turns it off. A kind with
no preference is a notice about the account itself -- the trial ending, a failed
payment, a renewal -- which every admin gets, as with any service they pay for.
"""

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _

BANK_CONNECTION = "bank_connection"
BUDGET_OVERSPENT = "budget_overspent"
TRIAL_ENDING = "trial_ending"
PAYMENT_FAILED = "payment_failed"
RENEWAL_UPCOMING = "renewal_upcoming"

#: `EmailPreferences` fields, each turning off one family of emails.
PREF_BANK_CONNECTION = "bank_connection_alerts"
PREF_BUDGET = "budget_alerts"

#: What the unsubscribe page says a preference stops.
PREFERENCE_LABELS = {
    PREF_BANK_CONNECTION: _("bank connection alerts"),
    PREF_BUDGET: _("overspending alerts"),
}


@dataclass(frozen=True)
class Kind:
    key: str
    template: str
    preference: str | None  # None: always sent


KINDS = {
    kind.key: kind
    for kind in (
        Kind(BANK_CONNECTION, "bank_connection", PREF_BANK_CONNECTION),
        Kind(BUDGET_OVERSPENT, "budget_overspent", PREF_BUDGET),
        Kind(TRIAL_ENDING, "trial_ending", None),
        Kind(PAYMENT_FAILED, "payment_failed", None),
        Kind(RENEWAL_UPCOMING, "renewal_upcoming", None),
    )
}

KIND_CHOICES = [
    (BANK_CONNECTION, "Bank connection"),
    (BUDGET_OVERSPENT, "Budget overspent"),
    (TRIAL_ENDING, "Trial ending"),
    (PAYMENT_FAILED, "Payment failed"),
    (RENEWAL_UPCOMING, "Renewal upcoming"),
]
