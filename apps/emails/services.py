"""
The one way Koala Budget sends an email of its own: `send`.

`send` decides whether the person gets it (an active account, a confirmed
address, the kind not turned off), records it under its keys so it goes out
once, renders it in the person's language, and adds the unsubscribe headers an
optional email needs (RFC 8058 one-click, which Gmail and Yahoo require of bulk
senders). Callers in `alerts` decide what to say and to whom.
"""

import logging

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation

from apps.web.meta import absolute_url

from .kinds import KINDS, PREFERENCE_LABELS
from .models import EmailPreferences, SentEmail

logger = logging.getLogger(__name__)

UNSUBSCRIBE_SALT = "apps.emails.unsubscribe"


def can_receive(user) -> bool:
    """An active account whose sign-in address is confirmed (when the site confirms addresses at all)."""
    if not user.is_active or not user.email:
        return False
    if settings.ACCOUNT_EMAIL_VERIFICATION == "none":
        return True
    from allauth.account.models import EmailAddress

    return EmailAddress.objects.filter(user=user, email__iexact=user.email, verified=True).exists()


def wants(user, kind) -> bool:
    """Whether the person left this kind of email on."""
    return kind.preference is None or getattr(EmailPreferences.for_user(user), kind.preference)


def unsubscribe_token(user, preference) -> str:
    """A link token that turns `preference` off for `user`. It doesn't expire: an old email's link must still work."""
    return signing.dumps({"u": user.pk, "p": preference}, salt=UNSUBSCRIBE_SALT, compress=True)


def read_unsubscribe_token(token) -> tuple[int, str] | None:
    """(user id, preference) from a token, or None when it is not one of ours."""
    try:
        data = signing.loads(token, salt=UNSUBSCRIBE_SALT)
    except signing.BadSignature:
        return None
    if not isinstance(data, dict) or data.get("p") not in PREFERENCE_LABELS or not isinstance(data.get("u"), int):
        return None
    return data["u"], data["p"]


def unsubscribe_url(user, preference) -> str:
    return absolute_url(reverse("emails:unsubscribe", args=[unsubscribe_token(user, preference)]))


def preferences_url() -> str:
    return absolute_url(reverse("emails:preferences"))


def render(user, kind, context) -> EmailMultiAlternatives:
    """The message, rendered in the person's language."""
    context = {
        "user": user,
        "project_name": settings.PROJECT_METADATA["NAME"],
        "preferences_url": preferences_url(),
        **context,
    }
    headers = {}
    if kind.preference:
        link = unsubscribe_url(user, kind.preference)
        context["unsubscribe_url"] = link
        headers = {"List-Unsubscribe": f"<{link}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    with translation.override(user.language or settings.LANGUAGE_CODE):
        subject = " ".join(render_to_string(f"emails/{kind.template}_subject.txt", context).split())
        text = render_to_string(f"emails/{kind.template}.txt", context)
        html = render_to_string(f"emails/{kind.template}.html", context)
    message = EmailMultiAlternatives(
        subject=subject, body=text, from_email=settings.DEFAULT_FROM_EMAIL, to=[user.email], headers=headers
    )
    message.attach_alternative(html, "text/html")
    return message


def send(user, kind_key, context, *, keys, book=None) -> bool:
    """
    Send `kind_key` to `user` unless they can't or don't want it, or it already
    went out under every one of `keys`. Returns whether it was sent.

    The keys are recorded before sending, so two workers racing on the same alert
    send it once; a failed send removes them again, so a retry sends it.
    """
    kind = KINDS[kind_key]
    if not keys:
        raise ValueError("An email needs at least one key to be sent once.")
    if not can_receive(user) or not wants(user, kind):
        return False
    created = []
    for key in keys:
        record, was_created = SentEmail.objects.get_or_create(
            user=user, kind=kind.key, key=key, defaults={"book": book}
        )
        if was_created:
            created.append(record.pk)
    if not created:
        return False
    try:
        render(user, kind, context).send()
    except Exception:
        SentEmail.objects.filter(pk__in=created).delete()
        raise
    logger.info("Sent %s email to user %s", kind.key, user.pk)
    return True
