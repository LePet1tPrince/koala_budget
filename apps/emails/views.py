from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt

from .forms import EmailPreferencesForm
from .kinds import PREFERENCE_LABELS
from .models import EmailPreferences
from .services import read_unsubscribe_token


@login_required
def preferences(request):
    instance = EmailPreferences.for_user(request.user)
    form = EmailPreferencesForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Email preferences saved."))
        return redirect("emails:preferences")
    return render(
        request,
        "emails/preferences.html",
        {
            "form": form,
            "active_tab": "settings",
            "settings_section": "emails",
            "settings_page_title": _("Email notifications"),
            "settings_page_blurb": _("Choose which alerts Koala Budget emails you."),
            "page_title": _("Email notifications"),
        },
    )


def _mask(email):
    name, _sep, domain = email.partition("@")
    return f"{name[:1]}{'•' * max(len(name) - 1, 2)}@{domain}"


@csrf_exempt
def unsubscribe(request, token):
    """
    The link in an optional email's footer and its `List-Unsubscribe` header.

    No sign-in: the signed token is the authority, and it can only turn one
    preference off. A GET asks first (mail scanners follow links); a POST --
    the button, or a mail client's RFC 8058 one-click request, which carries no
    CSRF token -- turns it off.
    """
    parsed = read_unsubscribe_token(token)
    user = get_user_model().objects.filter(pk=parsed[0]).first() if parsed else None
    if user is None:
        return render(request, "emails/unsubscribe_invalid.html", status=400)
    preference = parsed[1]
    context = {"label": PREFERENCE_LABELS[preference], "masked_email": _mask(user.email)}
    if request.method == "POST":
        prefs = EmailPreferences.for_user(user)
        setattr(prefs, preference, False)
        prefs.save()
        return render(request, "emails/unsubscribe_done.html", context)
    return render(request, "emails/unsubscribe_confirm.html", context)
