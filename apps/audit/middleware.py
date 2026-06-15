from apps.audit.utils import set_current_user


class AuditUserMiddleware:
    """Stash the authenticated request user in thread-local storage so model
    signals (which have no request) can attribute audit records to a user."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            set_current_user(user)
        else:
            set_current_user(None)
        try:
            response = self.get_response(request)
        finally:
            set_current_user(None)
        return response
