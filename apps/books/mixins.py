from django.utils.decorators import method_decorator

from .decorators import book_admin_required, login_and_book_required


class BookObjectViewMixin:
    """For class-based views over a `BaseBookModel`: only this book's rows."""

    def get_queryset(self):
        return self.model.for_book.all()


class LoginAndBookRequiredMixin(BookObjectViewMixin):
    """The user is signed in and a member of the team whose book the URL names."""

    @method_decorator(login_and_book_required)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)


class BookAdminRequiredMixin(BookObjectViewMixin):
    """The user is signed in and an admin of the team whose book the URL names."""

    @method_decorator(book_admin_required)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)
