import time

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render


class AuthRateLimitMiddleware:
    """Rate limit authentication endpoints (login, signup, password reset).

    Uses Django's cache backend (Redis in production) to track request counts
    per IP address. Returns 429 Too Many Requests if the limit is exceeded.

    Settings (with defaults):
        AUTH_RATE_LIMIT_MAX_REQUESTS = 10
        AUTH_RATE_LIMIT_WINDOW_SECONDS = 300  (5 minutes)
    """

    AUTH_PATHS = (
        "/accounts/login/",
        "/accounts/signup/",
        "/accounts/password/reset/",
        "/accounts/password/reset/key/",
        "/accounts/confirm-email/",
        "/_allauth/",
    )

    def __init__(self, get_response):
        self.get_response = get_response
        self.max_requests = getattr(settings, "AUTH_RATE_LIMIT_MAX_REQUESTS", 10)
        self.window = getattr(settings, "AUTH_RATE_LIMIT_WINDOW_SECONDS", 300)

    def __call__(self, request):
        if request.method == "POST" and self._is_auth_path(request.path):
            ip = self._get_client_ip(request)
            cache_key = f"auth_ratelimit:{ip}"

            request_log = cache.get(cache_key, [])
            now = time.time()

            # Remove expired entries
            request_log = [t for t in request_log if now - t < self.window]

            if len(request_log) >= self.max_requests:
                retry_after = int(self.window - (now - request_log[0]))
                response = render(request, "429.html", status=429)
                response["Retry-After"] = str(max(retry_after, 1))
                return response

            request_log.append(now)
            cache.set(cache_key, request_log, self.window)

        return self.get_response(request)

    def _is_auth_path(self, path):
        return any(path.startswith(p) for p in self.AUTH_PATHS)

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")


# allauth's headless views (`/_allauth/{browser,app}/v1/...`) read the token
# themselves and swap the session for the request's duration; resolving it here
# too would hand them a user they did not load.
HEADLESS_PATH_PREFIX = "/_allauth/"


class SessionTokenMiddleware:
    """
    Sign in a request that carries an allauth `X-Session-Token` header (the phone app).

    Must sit right after `AuthenticationMiddleware` and before anything that reads
    `request.user`: `AuditUserMiddleware` stashes the user for the audit signals
    before any view (or DRF authentication) runs, and the teams/books middleware
    resolve membership from it. Done in DRF alone, every token write would be
    audited as nobody, and the plain-Django JSON views would not see the user.

    A cookie session wins: a request that is already signed in by cookie is left
    exactly as it is, CSRF and all. Otherwise a valid token (looked up with
    allauth's own token strategy, the one that issued it) becomes `request.user`,
    and for the length of the request `request.session` is the token's session, so
    the per-user conveniences kept there (`team`, `book_by_team`) follow the token
    rather than landing in a throwaway cookie session. The cookie session is put
    back before the response leaves, so no `Set-Cookie` carries the token out.

    CSRF is waived only for a request authenticated this way: a header is never
    sent by a browser on its own, so the forgery CSRF guards against cannot carry
    one. An unknown or expired token authenticates nothing; DRF answers it 401
    (`apps.api.authentication.SessionTokenAuthentication`), a page redirects to login.
    So does a token from before the user's password changed (`resolve_session_token`).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request.headers.get("X-Session-Token")
        if not token or request.path_info.startswith(HEADLESS_PATH_PREFIX) or request.user.is_authenticated:
            return self.get_response(request)

        from .authentication import resolve_session_token

        resolved = resolve_session_token(token)
        if resolved is None:
            return self.get_response(request)

        user, token_session = resolved
        cookie_session = request.session
        request.session = token_session
        request.user = user
        request._cached_user = user

        async def auser():
            return user

        request.auser = auser
        request.session_token_authenticated = True
        request._dont_enforce_csrf_checks = True
        try:
            return self.get_response(request)
        finally:
            # A logout during the request flushes the session; there is nothing to keep then.
            if token_session.modified and not token_session.is_empty():
                token_session.save()
            request.session = cookie_session


HEADLESS_APP_PATH_PREFIX = "/_allauth/app/"


class HeadlessAppUserMiddleware:
    """
    Let allauth's `app` endpoints (`/_allauth/app/v1/...`) see the token's user.

    allauth swaps in the token's session inside the view and re-evaluates the lazy
    `request.user` (`authkit.authentication_context`). `HijackUserMiddleware` wraps
    `request.user` around a copy of the user already resolved from the (empty) cookie
    session, so that re-evaluation came back anonymous: every signed-in `app` call
    -- session status, password change, re-authentication, MFA -- answered 401.
    Placed after `HijackUserMiddleware`, this gives those paths a `request.user` that
    reads whatever session the request holds when it is evaluated. Hijacking is a
    staff feature of the web app; the phone's auth endpoints never carry it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info.startswith(HEADLESS_APP_PATH_PREFIX):
            from django.contrib import auth
            from django.utils.functional import SimpleLazyObject

            request.user = SimpleLazyObject(lambda: auth.get_user(request))
        return self.get_response(request)
