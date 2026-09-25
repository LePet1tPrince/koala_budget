from django.urls import path

from . import views

# `/a/{team}/books/...` -- listing, creating, archiving and deleting sets of books
# are team-level actions, so a book can be managed without opening it. The book
# is `slug`, not `book_slug`: `BooksMiddleware` would otherwise treat these as
# pages *in* that book and remember it as the one last opened.
team_urlpatterns = (
    [
        path("", views.book_list, name="list"),
        path("new/", views.book_create, name="create"),
        path("<slug:slug>/archive/", views.book_archive, name="archive"),
        path("<slug:slug>/restore/", views.book_restore, name="restore"),
        path("<slug:slug>/delete/", views.book_delete, name="delete"),
    ],
    "books_team",
)

# `/a/{team}/{book}/settings/` -- the settings that belong to this set of books.
book_urlpatterns = (
    [
        path("", views.book_settings, name="settings"),
    ],
    "books",
)
