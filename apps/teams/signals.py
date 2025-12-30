from allauth.account.signals import user_signed_up
from django.db.models.signals import post_save
from django.db import transaction
from django.dispatch import receiver
from datetime import date

from .helpers import create_default_team_for_user, get_open_invitations_for_user
from .invitations import get_invitation_id_from_request, process_invitation
from .models import Invitation, Team
from .services.team_bootstrap import bootstrap_team
from apps.teams.services.template_engine import apply_template
from apps.teams.services.template_budget import PERSONAL_BUDGET_TEMPLATE


@receiver(user_signed_up)
def add_user_to_team(request, user, **kwargs):
    """
    Adds the user to the team if there is invitation information in the URL.
    """
    invitation_id = get_invitation_id_from_request(request)
    if invitation_id:
        try:
            invitation = Invitation.objects.get(id=invitation_id)
            process_invitation(invitation, user)
        except Invitation.DoesNotExist:
            # for now just swallow missing invitation errors
            # these should get picked up by the form validation
            pass
    elif not user.teams.exists() and not get_open_invitations_for_user(user):
        # If the sign up was from a social account, there may not be a default team, so create one unless
        # the user has open invitations
        create_default_team_for_user(user)

@receiver(post_save, sender=Team)
def bootstrap_team_on_create(sender, instance, created, **kwargs):
    if not created:
        return

    month_start = date.today().replace(day=1)

    apply_template(
        team=instance,
        template=PERSONAL_BUDGET_TEMPLATE,
        month_start=month_start,
    )
