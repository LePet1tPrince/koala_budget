"""DRF authentication for the phone app's allauth session token."""

from allauth.headless.contrib.rest_framework.authentication import XSessionTokenAuthentication
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import AuthenticationFailed

TOKEN_HEADER = "X-Session-Token"


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
        resolved = super().authenticate(request)
        if resolved is None:
            raise AuthenticationFailed(_("Invalid or expired session token."))
        return resolved

    def authenticate_header(self, request):
        if self.get_session_token(request):
            return TOKEN_HEADER
        return None
