"""
The one exception a feed service raises to refuse a request.

The feed's endpoints answer a refusal as `{"error": <message>}` with a 400, or a
404 when what the request named isn't in the book. The services decide which --
they are the ones that looked -- so the error carries its status, and the view
only turns it into a response (`views.error_response`).
"""


class FeedError(Exception):
    """A refused feed request: `message` is what the user sees, `status` the HTTP status."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = str(message)
        self.status = status

    @classmethod
    def not_found(cls, message):
        return cls(message, status=404)

