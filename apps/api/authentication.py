"""DRF authentication for the phone app's allauth session token."""

from allauth.headless.contrib.rest_framework.authentication import XSessionTokenAuthentication
from django.contrib.auth import HASH_SESSION_KEY
from django.utils.crypto import constant_time_compare
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import AuthenticationFailed

TOKEN_HEADER = "X-Session-Token"


def resolve_session_token(token: str):
    """
    The (user, session) an `X-Session-Token` names, or None.

    allauth's lookup (the token is its session's key; an inactive user is refused)
    plus the check Django makes of every cookie session: the session's auth hash
    must match the user's password. Without it a token taken before a password
    change or reset kept working after it, while every cookie session ended. A
    token that fails the check is flushed, so allauth's own endpoints drop it too.
    """
    from allauth.headless.internal.sessionkit import authenticate_by_x_session_token

    resolved = authenticate_by_x_session_token(token)
    if resolved is None:
        return None
    user, session = resolved
    session_hash = session.get(HASH_SESSION_KEY) or ""
    hashes = [user.get_session_auth_hash(), *user.get_session_auth_fallback_hash()]
    if session_hash and any(constant_time_compare(session_hash, known) for known in hashes):
        return user, session
    session.flush()
    return None


class SessionTokenAuthentication(XSessionTokenAuthentication):
    """
    allauth's `XSessionTokenAuthentication`, agreeing with `SessionTokenMiddleware`.

    * A token the middleware already resolved is used as is (no second lookup).
    * A cookie session wins over a header token, as it does in the middleware, so
      DRF and the audit log can never disagree about who made a request.
    * A header token that resolves to nobody is a 401 rather than an anonymous
      request: the client sent credentials and should learn they are no good
      (to sign in again), not get a 403 that reads as "not allowed".

    Listed first in `DEFAULT_AUTHENTICATION_CLASSES` so its `WWW-Authenticate`
    turns that failure into a 401; for a request with no token header it returns
    nothing and adds no header, so browser responses are unchanged (403).
    """

    def authenticate(self, request):
        django_request = request._request
        if getattr(django_request, "session_token_authenticated", False):
            return (django_request.user, None)
        if not self.get_session_token(request):
            return None
        if django_request.user.is_authenticated:
            return None
        resolved = resolve_session_token(self.get_session_token(request))
        if resolved is None:
            raise AuthenticationFailed(_("Invalid or expired session token."))
        return resolved

    def authenticate_header(self, request):
        if self.get_session_token(request):
            return TOKEN_HEADER
        return None
