from django.urls import path
from django.views.generic import TemplateView

from . import views

app_name = "web"
urlpatterns = [
    path("", views.home, name="home"),
    path("terms/", TemplateView.as_view(template_name="web/terms.html"), name="terms"),
    path("privacy/", TemplateView.as_view(template_name="web/privacy.html"), name="privacy"),
    path("robots.txt", TemplateView.as_view(template_name="robots.txt", content_type="text/plain"), name="robots.txt"),
    # these views are just for testing error pages
    # actual error handling is handled by Django: https://docs.djangoproject.com/en/stable/ref/views/#error-views
    path("400/", TemplateView.as_view(template_name="400.html"), name="400"),
    path("403/", TemplateView.as_view(template_name="403.html"), name="403"),
    path("404/", TemplateView.as_view(template_name="404.html"), name="404"),
    path("429/", TemplateView.as_view(template_name="429.html"), name="429"),
    path("500/", TemplateView.as_view(template_name="500.html"), name="500"),
    path("simulate_error/", views.simulate_error),
    path("health/", views.HealthCheck.as_view(), name="health_check"),
]


# `/a/{team}/` -- the team's root sends the user on to the book they last opened.
team_urlpatterns = (
    [
        path("", views.team_home, name="home"),
        path("settings/", views.settings_home, name="settings"),
    ],
    "web_team",
)

# `/a/{team}/{book}/` -- the dashboard of one set of books.
book_urlpatterns = (
    [
        path("", views.book_home, name="home"),
    ],
    "web_book",
)
