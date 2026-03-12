from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _


def send_welcome_email(user, request=None):
    project_name = settings.PROJECT_METADATA["NAME"]

    if request is not None:
        from django.urls import reverse

        login_url = request.build_absolute_uri(reverse("account_login"))
    else:
        login_url = settings.FRONTEND_ADDRESS

    email_context = {
        "user": user,
        "project_name": project_name,
        "login_url": login_url,
    }
    send_mail(
        subject=_("Welcome to {}!").format(project_name),
        message=render_to_string("users/email/welcome_message.txt", context=email_context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
        html_message=render_to_string("users/email/welcome_message.html", context=email_context),
    )
