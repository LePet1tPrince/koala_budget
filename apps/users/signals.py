from allauth.account.models import EmailAddress
from allauth.account.signals import email_confirmed, user_signed_up
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.mail import mail_admins
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from apps.users.emails import send_welcome_email
from apps.users.models import CustomUser


@receiver(user_signed_up)
def handle_sign_up(request, user, **kwargs):
    _notify_admins_of_signup(user)
    # Send a welcome email immediately when email verification is not required.
    # When verification is mandatory, the welcome email is sent after confirmation instead.
    if settings.ACCOUNT_EMAIL_VERIFICATION != "mandatory":
        send_welcome_email(user, request=request)


@receiver(email_confirmed)
def update_user_email(sender, request, email_address, **kwargs):
    """
    When an email address is confirmed make it the primary email.
    """
    # This also sets user.email to the new email address.
    # hat tip: https://stackoverflow.com/a/29661871/8207
    email_address.set_as_primary()

    # Send a welcome email the first time a user confirms their email address.
    user = email_address.user
    confirmed_count = EmailAddress.objects.filter(user=user, verified=True).count()
    if confirmed_count == 1:
        send_welcome_email(user, request=request)


def _notify_admins_of_signup(user):
    mail_admins(
        f"Yowsers, someone signed up for {settings.PROJECT_METADATA['NAME']}!",
        f"Email: {user.email}",
        fail_silently=True,
    )


@receiver(pre_save, sender=CustomUser)
def remove_old_profile_picture_on_change(sender, instance, **kwargs):
    if not instance.pk:
        return False

    try:
        old_file = sender.objects.get(pk=instance.pk).avatar
    except sender.DoesNotExist:
        return False

    if old_file and old_file.name != instance.avatar.name and default_storage.exists(old_file.name):
        default_storage.delete(old_file.name)


@receiver(post_delete, sender=CustomUser)
def remove_profile_picture_on_delete(sender, instance, **kwargs):
    if instance.avatar and default_storage.exists(instance.avatar.name):
        default_storage.delete(instance.avatar.name)
