from django.urls import path

from . import views

# `/a/{team}/books/...` -- listing and creating sets of books are team-level
# actions: there is no one book in the URL.
team_urlpatterns = (
    [
        path("", views.book_list, name="list"),
        path("new/", views.book_create, name="create"),
    ],
    "books_team",
)

# `/a/{team}/{book}/settings/...` -- settings that belong to this set of books.
book_urlpatterns = (
    [
        path("", views.book_settings, name="settings"),
        path("budgeting/", views.book_budgeting, name="budgeting"),
        path("archive/", views.book_archive, name="archive"),
        path("restore/", views.book_restore, name="restore"),
        path("delete/", views.book_delete, name="delete"),
    ],
    "books",
)
