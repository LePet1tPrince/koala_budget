"""
The rules that keep a reconciled line reconciled.

The reconciliation guarantee rests on one claim: a line confirmed against a
statement does not change behind the user's back. Every write path that can
move, re-date, re-amount, delete or void a journal line asks these functions
first -- the bank feed, the journal API, and whatever manual-entry surface
comes next -- so the rule is stated once rather than at each call site.

`ReconciledLineError` subclasses ValueError because the feed's endpoints
already turn a ValueError into a 400; the message is shown to the user and says
what to do.
"""

from django.utils.translation import gettext as _


class ReconciledLineError(ValueError):
    """A change that would alter a reconciled line."""


def _reconciled(lines):
    return [line for line in lines if line.is_reconciled]


def _refuse(own: bool, verb: str):
    if own:
        raise ReconciledLineError(_("This transaction is reconciled. Unreconcile it before %(verb)s.") % {"verb": verb})
    raise ReconciledLineError(
        _("The other side of this transfer is already reconciled. Unreconcile the other transaction before %(verb)s.")
        % {"verb": verb}
    )


def reconciled_lines(entry):
    """The entry's reconciled lines (a list; [] for no entry)."""
    if entry is None:
        return []
    return _reconciled(entry.lines.all())


def assert_entry_removable(entry, *, own_account_id=None, verb=None):
    """
    Refuse to delete or void an entry that carries a reconciled line.

    `own_account_id` names the account the user is acting from, so the message
    can say whether it is their line or the other side of a transfer.
    """
    verb = verb or _("removing it")
    for line in reconciled_lines(entry):
        _refuse(own_account_id is None or line.account_id == own_account_id, verb)


def assert_line_removable(line, *, own=True, verb=None):
    """Refuse to delete one reconciled line."""
    if line.is_reconciled:
        _refuse(own, verb or _("removing it"))


def assert_entry_voidable(entry):
    """Voiding drops every line out of every balance -- including reconciled ones."""
    assert_entry_removable(entry, verb=_("voiding it"))


def assert_line_mutable(line, *, new_account=None, new_amount=None, own=True):
    """
    Refuse to move a reconciled line to another account or change its amount.

    `new_amount` is the line's new signed amount (dr - cr); None means unchanged.
    """
    if not line.is_reconciled:
        return
    new_account_id = getattr(new_account, "id", new_account)
    if new_account_id is not None and new_account_id != line.account_id:
        _refuse(own, _("moving it to another account"))
    if new_amount is not None and new_amount != line.dr_amount - line.cr_amount:
        _refuse(own, _("changing its amount"))


def assert_date_change_allowed(entry, new_date):
    """
    Refuse to re-date an entry past the statement that reconciled one of its lines.

    A line reconciled on the Aug 31 statement cannot become a September
    transaction without the statement becoming false. Re-dating within the
    statement period, or a line reconciled before statements existed, is fine.
    """
    if entry is None or new_date is None or new_date == entry.entry_date:
        return
    for line in entry.lines.select_related("reconciliation").filter(is_reconciled=True):
        rec = line.reconciliation
        if rec is not None and rec.is_completed and new_date > rec.statement_date:
            raise ReconciledLineError(
                _(
                    "This transaction is reconciled on the %(date)s statement. "
                    "Unreconcile it before moving it past that date."
                )
                % {"date": rec.statement_date.isoformat()}
            )
