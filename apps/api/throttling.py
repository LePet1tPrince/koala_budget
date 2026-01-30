from rest_framework.throttling import AnonRateThrottle


class AuthRateThrottle(AnonRateThrottle):
    """Stricter rate limit for authentication endpoints (login, signup, password reset).

    Uses the 'auth' rate from REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'].
    Keyed by IP address to prevent brute-force attacks.
    """

    scope = "auth"
