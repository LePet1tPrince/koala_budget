from allauth.socialaccount.models import SocialAccount
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from . import services
from .adapter import user_has_valid_totp_device
from .forms import CustomUserChangeForm


@login_required
def profile(request):
    if request.method == "POST":
        form = CustomUserChangeForm(request.POST, instance=request.user)
        if form.is_valid():
            user = form.save(commit=False)
            if services.save_profile(request, user):
                # recreate the form to avoid populating the unconfirmed email in the returned page
                form = CustomUserChangeForm(instance=user)

            user_language = user.language
            if user_language and user_language != translation.get_language():
                translation.activate(user_language)
            if user.timezone != timezone.get_current_timezone():
                if user.timezone:
                    timezone.activate(user.timezone)
                else:
                    timezone.deactivate()
            messages.success(request, _("Profile successfully saved."))
    else:
        form = CustomUserChangeForm(instance=request.user)
    return render(
        request,
        "account/profile.html",
        {
            "form": form,
            "active_tab": "settings",
            "settings_section": "profile",
            "settings_page_title": _("Profile"),
            "page_title": _("Profile"),
            "api_keys": request.user.api_keys.filter(revoked=False),
            "social_accounts": SocialAccount.objects.filter(user=request.user),
            "user_has_valid_totp_device": user_has_valid_totp_device(request.user),
            "now": timezone.now(),
            "current_tz": timezone.get_current_timezone(),
        },
    )


@login_required
@require_POST
def create_api_key(request):
    _api_key, key = services.create_api_key(request.user)
    messages.success(
        request,
        _("API Key created. Your key is: {key}. Save this somewhere safe - you will only see it once!").format(
            key=key,
        ),
    )
    return HttpResponseRedirect(reverse("users:user_profile"))


@login_required
@require_POST
def revoke_api_key(request):
    key_id = request.POST.get("key_id")
    api_key = get_object_or_404(request.user.api_keys, id=key_id)
    services.revoke_api_key(api_key)
    messages.success(
        request,
        _("API Key {key} has been revoked. It can no longer be used to access the site.").format(
            key=api_key.prefix,
        ),
    )
    return HttpResponseRedirect(reverse("users:user_profile"))


@login_required
def delete_account(request):
    """Account deletion view with confirmation."""
    if request.method == "POST":
        confirmation = request.POST.get("confirmation", "")
        if confirmation == request.user.email:
            user = request.user
            # Signed out first: the logout's audit event needs the user to still exist.
            logout(request)
            services.delete_user_account(user)
            messages.success(request, _("Your account has been permanently deleted."))
            return HttpResponseRedirect(reverse("web:home"))
        else:
            messages.error(request, _("Email confirmation did not match. Account was not deleted."))

    return render(
        request,
        "account/delete_account.html",
        {
            "active_tab": "settings",
            "settings_section": "profile",
            "page_title": _("Delete Account"),
        },
    )
