from functools import wraps

from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from .roles import is_admin, is_member


def login_and_team_required(view_func):
    return _get_decorated_function(view_func, is_member)


def team_admin_required(view_func):
    return _get_decorated_function(view_func, is_admin)


def _get_decorated_function(view_func, permission_test_function):
    @wraps(view_func)
    def _inner(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return HttpResponseRedirect("{}?next={}".format(reverse("account_login"), request.path))

        team = request.team  # set by middleware
        if not team or not permission_test_function(user, team):
            # Treat not having access to a team (or a team slug that doesn't exist at
            # all) like a 404, to avoid accidentally leaking information. Rendered
            # directly, rather than `raise Http404`, so the visitor always sees our
            # friendly 404 page -- a bare `raise Http404` shows Django's raw technical
            # 404 page whenever DEBUG=True (e.g. local dev), regardless of the custom
            # 404.html template that's used in production.
            return render(request, "404.html", status=404)

        return view_func(request, *args, **kwargs)

    return _inner
