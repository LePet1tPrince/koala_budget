from django.urls import path

from . import views

# `/api/...` -- user-level and global endpoints (the per-app pattern keeps book data
# under `/a/{team}/{book}/{app}/api/` and team data under `/a/{team}/.../api/`).
# Mounted beside `api/schema/`, which is its own pattern: nothing here may be
# called `schema`.
app_name = "api"
urlpatterns = [
    path("me/", views.MeView.as_view(), name="me"),
]

# `/a/{team}/{book}/api/...` -- book endpoints that belong to no one app, such as
# the chrome's figures. Mounting this reserves `api` as a book slug.
book_urlpatterns = (
    [
        path("nav-state/", views.NavStateView.as_view(), name="nav_state"),
    ],
    "book_api",
)
