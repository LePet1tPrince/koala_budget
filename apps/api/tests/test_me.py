from django.test import TestCase
from django.urls import reverse

from apps.api.models import UserAPIKey
from apps.books.helpers import create_book
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

ME_URL = "/api/me/"


class MeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username="me@example.com", email="me@example.com", password="pass", first_name="Ada", language="fr"
        )
        cls.alpha = Team.objects.create(name="Alpha", slug="alpha")
        cls.alpha.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.beta = Team.objects.create(name="Beta", slug="beta")
        cls.beta.members.add(cls.user, through_defaults={"role": ROLE_MEMBER})
        cls.business = create_book(cls.alpha, "Business")
        cls.old = create_book(cls.alpha, "Old")
        cls.old.archive()
        cls.old.save()
        # Someone else's team: never listed.
        cls.stranger = CustomUser.objects.create_user(username="x@example.com", email="x@example.com", password="p")
        Team.objects.create(name="Gamma", slug="gamma").members.add(cls.stranger, through_defaults={"role": ROLE_ADMIN})

    def test_the_url_does_not_shadow_the_schema(self):
        self.assertEqual(reverse("api:me"), ME_URL)
        self.assertEqual(reverse("schema"), "/api/schema/")
        self.assertEqual(self.client.get("/api/schema/").status_code, 200)

    def test_user_teams_roles_and_books(self):
        self.client.force_login(self.user)
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, 200)
        body = response.json()

        user = body["user"]
        self.assertEqual(user["id"], self.user.id)
        self.assertEqual(user["email"], "me@example.com")
        self.assertEqual(user["display_name"], "Ada")
        self.assertEqual(user["language"], "fr")
        self.assertTrue(user["avatar_url"].startswith("https://www.gravatar.com/"))

        self.assertEqual([t["slug"] for t in body["teams"]], ["alpha", "beta"])
        alpha, beta = body["teams"]
        self.assertEqual(alpha["role"], ROLE_ADMIN)
        self.assertEqual(beta["role"], ROLE_MEMBER)
        books = {b["slug"]: b for b in alpha["books"]}
        self.assertEqual(set(books), {"personal", "business", "old"})
        self.assertTrue(books["personal"]["is_default"])
        self.assertFalse(books["business"]["is_default"])
        self.assertTrue(books["old"]["is_archived"])
        self.assertEqual(books["business"]["base_url"], "/a/alpha/business/")
        self.assertNotIn("gamma", [t["slug"] for t in body["teams"]])

    def test_default_is_where_the_web_app_lands(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(ME_URL).json()["default"], {"team": "alpha", "book": "personal"})
        # Opening a book in another team moves both, as it does for `/`.
        self.client.get(reverse("web_book:home", args=self.business.url_args))
        self.assertEqual(self.client.get(ME_URL).json()["default"], {"team": "alpha", "book": "business"})
        beta_book = self.beta.default_book
        self.client.get(reverse("web_book:home", args=beta_book.url_args))
        self.assertEqual(self.client.get(ME_URL).json()["default"], {"team": "beta", "book": beta_book.slug})

    def test_no_team_means_no_default(self):
        loner = CustomUser.objects.create_user(username="lone@example.com", email="lone@example.com", password="p")
        self.client.force_login(loner)
        body = self.client.get(ME_URL).json()
        self.assertEqual(body["teams"], [])
        self.assertIsNone(body["default"])

    def test_anonymous_is_refused(self):
        self.assertEqual(self.client.get(ME_URL).status_code, 403)

    def test_an_api_key_works(self):
        _key, raw = UserAPIKey.objects.create_key(name="phone", user=self.user)
        response = self.client.get(ME_URL, headers={"Authorization": f"Api-Key {raw}"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], self.user.id)
