"""Team-level API: memberships, resending an invitation, and accepting one."""

import json

from allauth.account.models import EmailAddress
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.teams.models import Invitation, Membership, Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser


def make_user(email):
    return CustomUser.objects.create_user(username=email, email=email, password="pass")


class TeamAPITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Red Sox", slug="sox")
        cls.admin = make_user("tito@redsox.test")
        cls.member = make_user("papi@redsox.test")
        cls.member2 = make_user("manny@redsox.test")
        cls.outsider = make_user("derek@yankees.test")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})
        cls.team.members.add(cls.member2, through_defaults={"role": ROLE_MEMBER})
        cls.admin_membership = Membership.objects.get(team=cls.team, user=cls.admin)
        cls.member_membership = Membership.objects.get(team=cls.team, user=cls.member)
        cls.member2_membership = Membership.objects.get(team=cls.team, user=cls.member2)

    def membership_url(self, membership=None):
        if membership is None:
            return reverse("single_team:membership-list", args=[self.team.slug])
        return reverse("single_team:membership-detail", args=[self.team.slug, membership.pk])

    def patch(self, url, body):
        return self.client.patch(url, data=json.dumps(body), content_type="application/json")


class TeamViewSetTest(TeamAPITestCase):
    """`/teams/api/teams/`: the user's own teams, outside any team's URLs (no `request.team`)."""

    def test_a_member_lists_and_reads_their_teams(self):
        self.client.force_login(self.member)
        listed = self.client.get(reverse("teams:team-list"))
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([t["slug"] for t in listed.json()["results"]], ["sox"])
        detail = self.client.get(reverse("teams:team-detail", args=[self.team.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["slug"], "sox")

    def test_only_an_admin_edits_the_team(self):
        self.client.force_login(self.member)
        self.assertEqual(
            self.patch(reverse("teams:team-detail", args=[self.team.pk]), {"name": "Nope"}).status_code, 403
        )
        self.client.force_login(self.admin)
        self.assertEqual(
            self.patch(reverse("teams:team-detail", args=[self.team.pk]), {"name": "Sox"}).status_code, 200
        )
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Sox")

    def test_an_outsider_sees_no_team(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("teams:team-list")).json()["results"], [])
        self.assertEqual(self.client.get(reverse("teams:team-detail", args=[self.team.pk])).status_code, 404)

    def test_anonymous_is_refused(self):
        self.assertIn(self.client.get(reverse("teams:team-list")).status_code, (401, 403))

    def test_creating_a_team_makes_the_user_its_admin(self):
        self.client.force_login(self.outsider)
        response = self.client.post(
            reverse("teams:team-list"), data=json.dumps({"name": "Yankees"}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        team = Team.objects.get(pk=response.json()["id"])
        self.assertEqual(Membership.objects.get(team=team, user=self.outsider).role, ROLE_ADMIN)


class MembershipListTest(TeamAPITestCase):
    def test_a_member_lists_the_team_by_email(self):
        self.client.force_login(self.member)
        response = self.client.get(self.membership_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["user_id"] for row in response.json()], [self.member2.id, self.member.id, self.admin.id])
        self.assertEqual(self.client.get(self.membership_url(self.admin_membership)).json()["role"], ROLE_ADMIN)

    def test_a_non_member_and_an_anonymous_user_are_refused(self):
        self.assertEqual(self.client.get(self.membership_url()).status_code, 403)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.membership_url()).status_code, 403)
        self.assertEqual(self.client.get(self.membership_url(self.member_membership)).status_code, 403)

    def test_another_teams_membership_is_a_404(self):
        other = Team.objects.create(name="Yankees", slug="yanks")
        other.members.add(self.outsider, through_defaults={"role": ROLE_ADMIN})
        theirs = Membership.objects.get(team=other)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.membership_url(theirs)).status_code, 404)
        self.assertEqual(self.client.delete(self.membership_url(theirs)).status_code, 404)
        self.assertTrue(Membership.objects.filter(pk=theirs.pk).exists())


class MembershipRoleTest(TeamAPITestCase):
    def test_an_admin_changes_a_members_role(self):
        self.client.force_login(self.admin)
        response = self.patch(self.membership_url(self.member_membership), {"role": ROLE_ADMIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], ROLE_ADMIN)
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, ROLE_ADMIN)

    def test_an_unknown_role_is_refused(self):
        self.client.force_login(self.admin)
        response = self.patch(self.membership_url(self.member_membership), {"role": "owner"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("role", response.json())

    def test_nobody_changes_their_own_role(self):
        self.client.force_login(self.admin)
        response = self.patch(self.membership_url(self.admin_membership), {"role": ROLE_MEMBER})
        self.assertEqual(response.status_code, 400)
        self.admin_membership.refresh_from_db()
        self.assertEqual(self.admin_membership.role, ROLE_ADMIN)

    def test_a_member_cannot_change_roles(self):
        self.client.force_login(self.member)
        for membership in (self.member2_membership, self.member_membership):
            with self.subTest(membership=membership):
                response = self.patch(self.membership_url(membership), {"role": ROLE_ADMIN})
                self.assertEqual(response.status_code, 403)
        self.assertEqual(Membership.objects.filter(team=self.team, role=ROLE_ADMIN).count(), 1)

    def test_put_is_not_offered(self):
        self.client.force_login(self.admin)
        response = self.client.put(
            self.membership_url(self.member_membership),
            data=json.dumps({"role": ROLE_ADMIN}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 405)


class MembershipRemoveTest(TeamAPITestCase):
    def test_an_admin_removes_a_member(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.delete(self.membership_url(self.member_membership)).status_code, 204)
        self.assertFalse(Membership.objects.filter(pk=self.member_membership.pk).exists())

    def test_a_member_may_leave(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.delete(self.membership_url(self.member_membership)).status_code, 204)
        self.assertFalse(Membership.objects.filter(pk=self.member_membership.pk).exists())

    def test_a_member_cannot_remove_someone_else(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.delete(self.membership_url(self.member2_membership)).status_code, 403)
        self.assertEqual(self.client.delete(self.membership_url(self.admin_membership)).status_code, 403)
        self.assertEqual(Membership.objects.filter(team=self.team).count(), 3)

    def test_the_only_admin_cannot_be_removed(self):
        self.client.force_login(self.admin)
        response = self.client.delete(self.membership_url(self.admin_membership))
        self.assertEqual(response.status_code, 400)
        self.assertIn("non_field_errors", response.json())
        self.assertTrue(Membership.objects.filter(pk=self.admin_membership.pk).exists())

    def test_an_admin_may_leave_once_there_is_another(self):
        self.member_membership.role = ROLE_ADMIN
        self.member_membership.save()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.delete(self.membership_url(self.admin_membership)).status_code, 204)


class ResendInvitationTest(TeamAPITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.invitation = Invitation.objects.create(team=cls.team, email="new@redsox.test", invited_by=cls.admin)

    def url(self, invitation=None):
        invitation = invitation or self.invitation
        return reverse("single_team:invitation-resend", args=[invitation.team.slug, invitation.id])

    def test_an_admin_resends(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "new@redsox.test")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new@redsox.test"])

    def test_a_member_and_a_non_member_cannot(self):
        for user in (self.member, self.outsider):
            with self.subTest(user=user):
                self.client.force_login(user)
                self.assertEqual(self.client.post(self.url()).status_code, 403)
        self.assertEqual(mail.outbox, [])

    def test_another_teams_invitation_is_a_404(self):
        other = Team.objects.create(name="Yankees", slug="yanks")
        theirs = Invitation.objects.create(team=other, email="x@yanks.test", invited_by=self.outsider)
        self.client.force_login(self.admin)
        response = self.client.post(reverse("single_team:invitation-resend", args=[self.team.slug, theirs.id]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(mail.outbox, [])


class AcceptInvitationAPITest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Red Sox", slug="sox")
        cls.admin = make_user("tito@redsox.test")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.invitee = make_user("new@redsox.test")
        EmailAddress.objects.create(user=cls.invitee, email="new@redsox.test", verified=True, primary=True)
        cls.invitation = Invitation.objects.create(
            team=cls.team, email="new@redsox.test", role=ROLE_MEMBER, invited_by=cls.admin
        )

    def url(self, invitation=None):
        return reverse("teams:invitation_api", args=[(invitation or self.invitation).id])

    def test_the_invitee_reads_and_accepts_it(self):
        self.client.force_login(self.invitee)
        details = self.client.get(self.url()).json()
        self.assertEqual(details["team_name"], "Red Sox")
        self.assertTrue(details["can_accept"])
        self.assertIsNone(details["cannot_accept_reason"])

        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"team_id": self.team.id, "team_slug": "sox", "team_name": "Red Sox", "role": ROLE_MEMBER, "joined": True},
        )
        self.assertTrue(Membership.objects.filter(team=self.team, user=self.invitee, role=ROLE_MEMBER).exists())
        self.invitation.refresh_from_db()
        self.assertTrue(self.invitation.is_accepted)
        self.assertEqual(self.invitation.accepted_by, self.invitee)

        # Again: already a member, nothing to do.
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["joined"])

    def test_an_unverified_address_cannot_accept(self):
        EmailAddress.objects.filter(user=self.invitee).update(verified=False)
        self.client.force_login(self.invitee)
        self.assertFalse(self.client.get(self.url()).json()["can_accept"])
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Membership.objects.filter(team=self.team, user=self.invitee).exists())

    def test_someone_else_cannot_accept_it(self):
        stranger = make_user("stranger@example.test")
        EmailAddress.objects.create(user=stranger, email="stranger@example.test", verified=True, primary=True)
        self.client.force_login(stranger)
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Membership.objects.filter(team=self.team, user=stranger).exists())
        self.invitation.refresh_from_db()
        self.assertFalse(self.invitation.is_accepted)

    def test_an_accepted_invitation_is_refused(self):
        self.invitation.is_accepted = True
        self.invitation.save()
        self.client.force_login(self.invitee)
        self.assertEqual(self.client.post(self.url()).status_code, 400)
        self.assertFalse(Membership.objects.filter(team=self.team, user=self.invitee).exists())

    def test_anonymous_and_unknown(self):
        self.assertEqual(self.client.post(self.url()).status_code, 403)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.client.force_login(self.invitee)
        unknown = reverse("teams:invitation_api", args=["00000000-0000-0000-0000-000000000000"])
        self.assertEqual(self.client.post(unknown).status_code, 404)

    def test_an_api_key_cannot_accept(self):
        from apps.api.models import UserAPIKey

        _key, key = UserAPIKey.objects.create_key(name="k", user=self.invitee)
        response = self.client.post(self.url(), HTTP_AUTHORIZATION=f"Api-Key {key}")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Membership.objects.filter(team=self.team, user=self.invitee).exists())
