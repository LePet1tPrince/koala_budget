"""
`Refused`: the base of every domain error whose message is meant for the user.

A DRF view lets one propagate; `apps.api.exceptions.exception_handler` answers it
as `{"error": message}` with the class's `status_code`.
"""


class Refused(ValueError):
    status_code = 400
