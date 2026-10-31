"""Linking a bank into a book, keeping its account list current, and unlinking it."""

import logging

from django.db import transaction

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event

from . import services
from .models import PlaidAccount, PlaidItem
from .services import account_currency

logger = logging.getLogger(__name__)


class DuplicateItem(Exception):
    """The bank login is already linked in this book."""

    def __init__(self, item):
        self.item = item
        super().__init__(f"{item.institution_name} is already linked in this set of books.")


def find_duplicate(book, institution_id, accounts):
    """
    The book's existing link to the same bank login, judged as Plaid suggests:
    same institution and an account with the same name and mask. None if new.

    Linking a bank twice creates a second Plaid item whose transactions have new
    ids, so every transaction would be imported again -- and Plaid bills per item.
    Existing links made before institution_id was stored can't be matched.
    """
    if not institution_id:
        return None
    wanted = {((a.get("name") or "").strip().lower(), a.get("mask") or "") for a in accounts or ()}
    for item in PlaidItem.objects.filter(book=book, institution_id=institution_id).prefetch_related("accounts"):
        have = {(a.name.strip().lower(), a.mask or "") for a in item.accounts.all()}
        if not wanted or wanted & have:
            return item
    return None


def link_item(book, *, public_token, institution_id, institution_name, accounts=(), user=None):
    """
    Exchange Link's public token and record the new item and its accounts.

    Refuses (DuplicateItem) before exchanging when the login is already linked,
    so no second item is ever created at Plaid. If anything fails after the
    exchange, the new item is removed at Plaid again rather than left behind,
    unrecorded but billed.
    """
    duplicate = find_duplicate(book, institution_id, accounts)
    if duplicate is not None:
        raise DuplicateItem(duplicate)

    exchange = services.exchange_public_token(public_token)
    access_token = exchange["access_token"]
    try:
        name = institution_name_for(institution_id, institution_name)
        plaid_accounts = services.get_accounts(access_token)
        with transaction.atomic():
            item = PlaidItem.objects.create(
                book=book,
                plaid_item_id=exchange["item_id"],
                access_token=access_token,
                institution_name=name,
                institution_id=institution_id or "",
            )
            created = add_accounts(item, plaid_accounts)
    except Exception:
        remove_at_plaid(access_token)
        raise

    log_event(
        AuditEvent.PLAID_ITEM_LINKED,
        user=user,
        book=book,
        metadata={"plaid_item_id": item.pk, "institution": name, "accounts": len(created)},
    )
    return item, created


def backfill_item(item):
    """
    Re-read the item's whole history, after an account was mapped.

    A sync skips transactions on unmapped accounts and its cursor moves past
    them, so mapping an account later would otherwise only ever import what
    arrives from then on. Clearing the cursor makes the next sync deliver every
    transaction again; the ones already imported are recognised by id and
    skipped, and the newly mapped account's history lands.
    """
    from .tasks import sync_plaid_transactions

    PlaidItem.objects.filter(pk=item.pk).update(cursor=None)
    transaction.on_commit(lambda: sync_plaid_transactions.delay(item.pk))


def institution_name_for(institution_id, fallback=None):
    """
    The institution's display name. A failed lookup must not fail the link --
    the bank is already connected at Plaid by then -- so Link's own metadata
    name stands in.
    """
    try:
        return services.get_institution(institution_id).get("name") or fallback or "Unknown Institution"
    except Exception:
        logger.warning("Plaid institution lookup failed for %s", institution_id, exc_info=True)
        return fallback or "Unknown Institution"


def unlink_item(item, *, user=None):
    """
    Disconnect a bank: delete it and its accounts here; deleting it removes it
    at Plaid too (so it stops billing and sending webhooks).

    The feed rows it imported stay -- they are the user's history, and any of
    them may be categorized or reconciled. Only the Plaid bookkeeping beside
    them (PlaidTransaction) goes, with the accounts.
    """
    book, pk, name = item.book, item.pk, item.institution_name
    item.delete()  # apps.plaid.signals removes it at Plaid once this commits
    log_event(AuditEvent.PLAID_ITEM_REMOVED, user=user, book=book, metadata={"plaid_item_id": pk, "institution": name})


def remove_at_plaid(access_token):
    """Remove an item at Plaid, best effort: tolerate one already gone, log anything else."""
    try:
        services.remove_item(access_token)
    except Exception as exc:
        if services.plaid_error_code(exc) in ("ITEM_NOT_FOUND", "INVALID_ACCESS_TOKEN"):
            return  # already gone at Plaid
        logger.exception("Could not remove a Plaid item at Plaid; it may still be billed")


def add_accounts(item, accounts) -> list[PlaidAccount]:
    """
    Create a PlaidAccount for each of Plaid's `accounts` the item doesn't have yet.

    New accounts start unmapped; the user maps each to a ledger account. Returns
    only the ones created, so update mode can offer just those for mapping.
    """
    known = set(item.accounts.values_list("plaid_account_id", flat=True))
    created = []
    for account in accounts:
        if account["account_id"] in known:
            continue
        created.append(
            PlaidAccount.objects.create(
                book=item.book,
                plaid_account_id=account["account_id"],
                item=item,
                account=None,
                name=account.get("name") or "",
                mask=account.get("mask") or "",
                subtype=str(account.get("subtype") or ""),
                type=str(account.get("type") or ""),
                iso_currency_code=account_currency(account),
            )
        )
    return created
