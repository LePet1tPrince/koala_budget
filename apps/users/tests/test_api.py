"""The signed-in user's account API: profile, picture, API keys, data download, deleting the account."""

import json
import shutil
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.api.models import UserAPIKey
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

PASSWORD = "correct horse battery"


def make_user(email="me@example.test", password=PASSWORD):
    return CustomUser.objects.create_user(username=email, email=email, password=password)


def patch_json(client, url, body, **extra):
    return client.patch(url, data=json.dumps(body), content_type="application/json", **extra)


class ProfileAPITest(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.url = reverse("users:api_profile")

    def test_read_the_profile(self):
        data = self.client.get(self.url).json()
        self.assertEqual(data["email"], "me@example.test")
        self.assertEqual(data["display_name"], "me@example.test")
        self.assertTrue(data["avatar_url"].startswith("http"))

    def test_change_names_and_time_zone(self):
        response = patch_json(self.client, self.url, {"first_name": "Ada", "timezone": "Europe/London"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["display_name"], "Ada")
        self.assertFalse(response.json()["email_confirmation_sent"])
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.timezone), ("Ada", "Europe/London"))

    def test_the_profile_forms_rules_apply(self):
        for body, field in (({"email": "not-an-email"}, "email"), ({"timezone": "Mars/Olympus"}, "timezone")):
            with self.subTest(body=body):
                response = patch_json(self.client, self.url, body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "me@example.test")

    @override_settings(ACCOUNT_EMAIL_VERIFICATION="mandatory")
    def test_a_new_email_waits_for_confirmation(self):
        response = patch_json(self.client, self.url, {"email": "new@example.test"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["email_confirmation_sent"])
        self.assertEqual(response.json()["email"], "me@example.test")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "me@example.test")

    def test_anonymous_and_api_key_requests_are_refused(self):
        _row, key = UserAPIKey.objects.create_key(name="k", user=self.user)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        response = patch_json(self.client, self.url, {"first_name": "Mallory"}, HTTP_AUTHORIZATION=f"Api-Key {key}")
        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "")


class AvatarUploadAPITest(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.user = make_user()
        self.client.force_login(self.user)
        self.url = reverse("users:api_profile_avatar")

    def test_upload_a_picture(self):
        with override_settings(MEDIA_ROOT=self.media):
            image = SimpleUploadedFile("me.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
            response = self.client.post(self.url, {"avatar": image})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.avatar.name.startswith("profile-pictures/"))
        self.assertIn("profile-pictures/", response.json()["avatar_url"])

    def test_a_non_image_is_refused(self):
        with override_settings(MEDIA_ROOT=self.media):
            response = self.client.post(self.url, {"avatar": SimpleUploadedFile("run.exe", b"MZ")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("avatar", response.json())
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)

    def test_anonymous_is_refused(self):
        self.client.logout()
        self.assertEqual(self.client.post(self.url, {}).status_code, 403)


class APIKeysAPITest(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user("other@example.test")
        self.client.force_login(self.user)

    def test_create_list_and_revoke(self):
        response = self.client.post(reverse("users:api-key-list"))
        self.assertEqual(response.status_code, 201)
        created = response.json()
        self.assertTrue(created["key"].startswith(created["prefix"]))
        # The key works, and is never shown again.
        self.assertTrue(UserAPIKey.objects.is_valid(created["key"]))
        listed = self.client.get(reverse("users:api-key-list")).json()
        self.assertEqual([row["prefix"] for row in listed], [created["prefix"]])
        self.assertNotIn("key", listed[0])

        response = self.client.post(reverse("users:api-key-revoke", args=[created["prefix"]]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["revoked"])
        self.assertEqual(self.client.get(reverse("users:api-key-list")).json(), [])
        self.assertFalse(UserAPIKey.objects.is_valid(created["key"]))

    def test_another_users_key_is_a_404(self):
        theirs, _key = UserAPIKey.objects.create_key(name="theirs", user=self.other)
        response = self.client.post(reverse("users:api-key-revoke", args=[theirs.prefix]))
        self.assertEqual(response.status_code, 404)
        theirs.refresh_from_db()
        self.assertFalse(theirs.revoked)

    def test_an_api_key_cannot_mint_another(self):
        _row, key = UserAPIKey.objects.create_key(name="k", user=self.user)
        self.client.logout()
        response = self.client.post(reverse("users:api-key-list"), HTTP_AUTHORIZATION=f"Api-Key {key}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(UserAPIKey.objects.filter(user=self.user).count(), 1)


class DownloadDataAPITest(TestCase):
    def test_a_zip_of_my_data(self):
        user = make_user()
        self.client.force_login(user)
        response = self.client.get(reverse("users:download_data"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("attachment;", response["Content-Disposition"])

    def test_anonymous_is_refused(self):
        self.assertEqual(self.client.get(reverse("users:download_data")).status_code, 403)


class DeleteAccountAPITest(TestCase):
    def setUp(self):
        self.user = make_user()
        self.team = Team.objects.create(name="Mine", slug="mine")
        self.team.members.add(self.user, through_defaults={"role": ROLE_ADMIN})
        self.url = reverse("users:api_delete_account")
        self.client.force_login(self.user)

    def post(self, body, **extra):
        return self.client.post(self.url, data=json.dumps(body), content_type="application/json", **extra)

    def test_the_email_and_the_password_delete_the_account(self):
        response = self.post({"confirmation": "me@example.test", "password": PASSWORD})
        self.assertEqual(response.status_code, 204)
        self.assertFalse(CustomUser.objects.filter(pk=self.user.pk).exists())
        # The sole member's team goes with it.
        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())
        # Signed out.
        self.assertEqual(self.client.get(reverse("users:api_profile")).status_code, 403)

    def test_a_wrong_email_or_password_deletes_nothing(self):
        for body, field in (
            ({"confirmation": "someone@example.test", "password": PASSWORD}, "confirmation"),
            ({"confirmation": "me@example.test"}, "password"),
            ({"confirmation": "me@example.test", "password": "guess"}, "password"),
        ):
            with self.subTest(body=body):
                response = self.post(body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        self.assertTrue(CustomUser.objects.filter(pk=self.user.pk).exists())

    def test_an_account_without_a_password_must_have_reauthenticated(self):
        self.user.set_unusable_password()
        self.user.save()
        self.client.force_login(self.user)
        target = "apps.users.api_views.did_recently_authenticate"
        with mock.patch(target, return_value=False):
            self.assertEqual(self.post({"confirmation": "me@example.test"}).status_code, 403)
        self.assertTrue(CustomUser.objects.filter(pk=self.user.pk).exists())
        with mock.patch(target, return_value=True):
            self.assertEqual(self.post({"confirmation": "me@example.test"}).status_code, 204)
        self.assertFalse(CustomUser.objects.filter(pk=self.user.pk).exists())

    def test_the_page_deletes_the_account_too(self):
        """The page's own delete (email typed out) signs out and deletes without an error."""
        response = self.client.post(reverse("users:delete_account"), {"confirmation": "me@example.test"})
        self.assertRedirects(response, reverse("web:home"), fetch_redirect_response=False)
        self.assertFalse(CustomUser.objects.filter(pk=self.user.pk).exists())

    def test_anonymous_and_api_key_requests_are_refused(self):
        _row, key = UserAPIKey.objects.create_key(name="k", user=self.user)
        self.client.logout()
        body = {"confirmation": "me@example.test", "password": PASSWORD}
        self.assertEqual(self.post(body).status_code, 403)
        self.assertEqual(self.post(body, HTTP_AUTHORIZATION=f"Api-Key {key}").status_code, 403)
        self.assertTrue(CustomUser.objects.filter(pk=self.user.pk).exists())
