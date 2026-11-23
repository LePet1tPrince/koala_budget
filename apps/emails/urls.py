from django.urls import path

from . import api_views, views

app_name = "emails"
urlpatterns = [
    path("preferences/", views.preferences, name="preferences"),
    path("unsubscribe/<str:token>/", views.unsubscribe, name="unsubscribe"),
    path("api/preferences/", api_views.EmailPreferencesView.as_view(), name="api_preferences"),
]
