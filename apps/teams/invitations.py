from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _

from apps.users.models import CustomUser

from .models import Invitation


def send_invitation(invitation):
    project_name = settings.PROJECT_METADATA["NAME"]
    email_context = {
        "invitation": invitation,
        "project_name": project_name,
    }
    send_mail(
        subject=_("You're invited to {}!").format(project_name),
        message=render_to_string("teams/email/invitation.txt", context=email_context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[invitation.email],
        fail_silently=False,
        html_message=render_to_string("teams/email/invitation.html", context=email_context),
    )


def process_invitation(invitation: Invitation, user: CustomUser):
    invitation.team.members.add(user, through_defaults={"role": invitation.role})
    invitation.is_accepted = True
    invitation.accepted_by = user
    invitation.save()


def get_invitation_id_from_request(request):
    return (
        # URL takes precedence over session/cookie
        request.GET.get("invitation_id") or request.session.get("invitation_id")
    )


def clear_invite_from_session(request):
    if "invitation_id" in request.session:
        del request.session["invitation_id"]


class InvitationNotAcceptable(Exception):
    """This user can't accept this invitation (yet); the message says why and what to do."""


def check_can_accept(invitation: Invitation, user: CustomUser):
    """
    Whether `user` may accept `invitation` -- the rule the invitation page states:
    an invitation not yet accepted, sent to an email address the user has added to
    their account and verified. (Being a member already is not an error: there is
    nothing to accept, and the caller sends them to the team.)
    """
    from allauth.account.models import EmailAddress

    if invitation.is_accepted:
        raise InvitationNotAcceptable(_("Sorry, it looks like that invitation has already been accepted or expired."))
    address = EmailAddress.objects.filter(user=user, email__iexact=invitation.email).first()
    if address is None:
        raise InvitationNotAcceptable(
            _(
                "This invitation was sent to {invite_email} but you're signed in as {user_email}. "
                "Add {invite_email} to your account and verify it to accept the invitation."
            ).format(invite_email=invitation.email, user_email=user.email)
        )
    if not address.verified:
        raise InvitationNotAcceptable(_("You must verify the email address before you can accept the invitation."))
