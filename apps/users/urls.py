from django.urls import path
from rest_framework.routers import SimpleRouter

from . import api_views, views

api_key_router = SimpleRouter()
api_key_router.register("api/api-keys", api_views.APIKeyViewSet, basename="api-key")

app_name = "users"
urlpatterns = [
    path("profile/", views.profile, name="user_profile"),
    path("api-keys/create/", views.create_api_key, name="create_api_key"),
    path("api-keys/revoke/", views.revoke_api_key, name="revoke_api_key"),
    # The page's "Download My Data" link and the API's download are one view.
    path("download-data/", api_views.DownloadDataView.as_view(), name="download_data"),
    path("delete-account/", views.delete_account, name="delete_account"),
    # `/users/api/...` -- the signed-in user's own account.
    path("api/profile/", api_views.ProfileView.as_view(), name="api_profile"),
    path("api/profile/avatar/", api_views.AvatarUploadView.as_view(), name="api_profile_avatar"),
    path("api/delete-account/", api_views.DeleteAccountView.as_view(), name="api_delete_account"),
    *api_key_router.urls,
]
