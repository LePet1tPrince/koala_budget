"""
The one write gate for books whose team isn't entitled (`entitlement`).

Every book URL is under `/a/{team_slug}/{book_slug}/`, so a request is a book
request exactly when its view takes `book_slug`. An unsafe one (POST, PUT, PATCH,
DELETE) from a member of an unentitled team is refused before the view runs:

* a classic HTML form post is redirected back with a message;
* anything else (fetch, the API client, DRF) gets a 402 with `{"error", "code"}`.

Non-members pass through so the view answers its usual 404. Requests that
authenticate inside DRF (not by session) are gated by `assert_book_writable` in
`apps.books.permissions`.
"""

from django.contrib import messages
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.teams.roles import ROLE_ADMIN

from .entitlement import is_entitled

SAFE_METHODS = ("GET", "HEAD", "OPTIONS", "TRACE")
FORM_CONTENT_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")
ERROR_CODE = "subscription_required"


READ_ONLY = _lazy("These books are read-only: the free trial has ended and there is no subscription.")


def read_only_message(request) -> str:
    if request.team_membership and request.team_membership.role == ROLE_ADMIN:
        return f"{READ_ONLY} {_('Subscribe to edit them.')}"
    return f"{READ_ONLY} {_('Ask a team admin to subscribe.')}"


def _is_form_post(request) -> bool:
    return (
        request.content_type in FORM_CONTENT_TYPES
        and request.headers.get("x-requested-with") != "XMLHttpRequest"
        and "/api/" not in request.path
        and request.accepts("text/html")
    )


def _back(request) -> str:
    referer = request.headers.get("referer", "")
    if referer and url_has_allowed_host_and_scheme(
        referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return referer
    return reverse("subscriptions_team:subscription_details", args=[request.team.slug])


class SubscriptionGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method in SAFE_METHODS or "book_slug" not in view_kwargs:
            return None
        # `team_membership` is None for a non-member, an anonymous user or no team.
        if not request.team_membership or is_entitled(request.team):
            return None

        message = read_only_message(request)
        if _is_form_post(request):
            messages.error(request, message)
            return HttpResponseRedirect(_back(request))
        return JsonResponse({"error": message, "code": ERROR_CODE}, status=402)
