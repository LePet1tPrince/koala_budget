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
