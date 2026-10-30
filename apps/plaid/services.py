"""
Plaid API service layer.
Handles all interactions with the Plaid API.
"""

import json

from django.conf import settings
from django.urls import reverse
from django.utils import translation
from plaid.api import plaid_api
from plaid.configuration import Configuration
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_update import LinkTokenCreateRequestUpdate
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.link_token_transactions import LinkTokenTransactions
from plaid.model.products import Products
from plaid.model.transactions_sync_request import TransactionsSyncRequest


def plaid_error_code(exc) -> str | None:
    """
    The `error_code` of a failed Plaid API call (e.g. ITEM_LOGIN_REQUIRED), or
    None when `exc` is not a Plaid API error or carries no readable body.
    """
    body = getattr(exc, "body", None)
    if not body:
        return None
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return None
    return data.get("error_code") if isinstance(data, dict) else None


def get_plaid_client():
    """Get configured Plaid API client."""
    configuration = Configuration(
        host=getattr(settings, "PLAID_ENV", "https://sandbox.plaid.com"),
        api_key={
            "clientId": getattr(settings, "PLAID_CLIENT_ID", ""),
            "secret": getattr(settings, "PLAID_SECRET", ""),
        },
    )
    api_client = plaid_api.PlaidApi(plaid_api.ApiClient(configuration))
    return api_client


def country_codes():
    """The countries Link offers banks from (`PLAID_COUNTRY_CODES`), as SDK values."""
    return [CountryCode(code.strip().upper()) for code in settings.PLAID_COUNTRY_CODES if code.strip()]


def link_language():
    """
    The language Plaid Link is shown in: the user's active language when Plaid
    supports it (`PLAID_LINK_LANGUAGES`), else the first supported one.

    French matters for Canada -- Quebec institutions present their own login in
    French, and Plaid's consent pane should match.
    """
    supported = [code.strip().lower() for code in settings.PLAID_LINK_LANGUAGES if code.strip()] or ["en"]
    active = (translation.get_language() or "").split("-")[0].lower()
    return active if active in supported else supported[0]


def webhook_url():
    """The URL Plaid posts this app's webhooks to (`PLAID_WEBHOOK_URL`, else derived)."""
    if settings.PLAID_WEBHOOK_URL:
        return settings.PLAID_WEBHOOK_URL
    from apps.web.meta import absolute_url

    return absolute_url(reverse("plaid_webhook"))


def _link_kwargs(user_id, client_name):
    """What every link token carries, new link or update mode."""
    kwargs = {
        "user": LinkTokenCreateRequestUser(client_user_id=str(user_id)),
        "client_name": client_name,
        "country_codes": country_codes(),
        "language": link_language(),
        "webhook": webhook_url(),
    }
    if settings.PLAID_REDIRECT_URI:
        kwargs["redirect_uri"] = settings.PLAID_REDIRECT_URI
    return kwargs


def link_token_request(user_id, client_name: str = "Koala Budget") -> LinkTokenCreateRequest:
    """
    The /link/token/create request for linking a new bank.

    Without `webhook` Plaid never notifies this app of new transactions, so the
    item would only ever sync when the user pressed Refresh.
    """
    kwargs = _link_kwargs(user_id, client_name)
    kwargs["products"] = [Products(product) for product in settings.PLAID_PRODUCTS]
    if "transactions" in settings.PLAID_PRODUCTS:
        kwargs["transactions"] = LinkTokenTransactions(days_requested=settings.PLAID_TRANSACTIONS_DAYS_REQUESTED)
    return LinkTokenCreateRequest(**kwargs)


def update_link_token_request(item, user_id, client_name: str = "Koala Budget") -> LinkTokenCreateRequest:
    """
    The /link/token/create request for Link's update mode on an existing item:
    the user signs in again, renews consent, or -- when the bank has accounts
    they haven't shared -- picks which to add. No `products` (Plaid refuses them
    in update mode); the item keeps the ones it has.
    """
    kwargs = _link_kwargs(user_id, client_name)
    kwargs["access_token"] = item.access_token
    if item.new_accounts_available:
        kwargs["update"] = LinkTokenCreateRequestUpdate(account_selection_enabled=True)
    return LinkTokenCreateRequest(**kwargs)


def create_update_link_token(item, user_id, client_name: str = "Koala Budget"):
    """A Link token that opens update mode for `item`."""
    response = get_plaid_client().link_token_create(update_link_token_request(item, user_id, client_name))
    return response["link_token"]


def create_link_token(user_id, client_name: str = "Koala Budget"):
    """
    Create a Plaid Link token for initializing Plaid Link.

    Args:
        user_id: Unique identifier for the user
        client_name: Name to display in Plaid Link

    Returns:
        Link token string
    """
    response = get_plaid_client().link_token_create(link_token_request(user_id, client_name))
    return response["link_token"]


def exchange_public_token(public_token: str):
    """
    Exchange a public token for an access token.

    Args:
        public_token: Public token from Plaid Link

    Returns:
        dict with 'access_token' and 'item_id'
    """
    client = get_plaid_client()

    request = ItemPublicTokenExchangeRequest(public_token=public_token)

    response = client.item_public_token_exchange(request)
    return {
        "access_token": response["access_token"],
        "item_id": response["item_id"],
    }


def remove_item(access_token: str):
    """Remove an item at Plaid (/item/remove): it stops syncing, billing and sending webhooks."""
    from plaid.model.item_remove_request import ItemRemoveRequest

    get_plaid_client().item_remove(ItemRemoveRequest(access_token=access_token))


def get_accounts(access_token: str):
    """
    Get accounts for a Plaid item.

    Args:
        access_token: Access token for the item

    Returns:
        List of account dicts
    """
    client = get_plaid_client()

    from plaid.model.accounts_get_request import AccountsGetRequest

    request = AccountsGetRequest(access_token=access_token)

    response = client.accounts_get(request)
    return response["accounts"]


def account_currency(account) -> str | None:
    """
    A Plaid account's currency, from its balances: the ISO code, or Plaid's
    unofficial code when there is no ISO one (e.g. crypto). None when unknown.
    """
    balances = account.get("balances") or {}
    return balances.get("iso_currency_code") or balances.get("unofficial_currency_code") or None


def get_institution(institution_id: str):
    """
    Get institution details.

    Args:
        institution_id: Plaid institution ID

    Returns:
        Institution dict
    """
    client = get_plaid_client()

    from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest

    request = InstitutionsGetByIdRequest(
        institution_id=institution_id,
        # Must include the institution's own country: a Canadian bank looked up
        # with only US is "not found", which used to fail the whole link.
        country_codes=country_codes(),
    )

    response = client.institutions_get_by_id(request)
    return response["institution"]


def get_webhook_verification_key(key_id: str) -> dict:
    """The JWK Plaid signs webhooks with, for a key id (/webhook_verification_key/get)."""
    from plaid.model.webhook_verification_key_get_request import WebhookVerificationKeyGetRequest

    response = get_plaid_client().webhook_verification_key_get(WebhookVerificationKeyGetRequest(key_id=key_id))
    key = response["key"]
    return key.to_dict() if hasattr(key, "to_dict") else dict(key)


def sync_transactions(access_token: str, cursor: str = None):
    """
    Sync transactions using Plaid's /transactions/sync endpoint.

    Args:
        access_token: Access token for the item
        cursor: Optional cursor for incremental sync

    Returns:
        dict with 'added', 'modified', 'removed', 'next_cursor', 'has_more'
    """
    client = get_plaid_client()

    request_kwargs = {"access_token": access_token}
    if cursor:
        request_kwargs["cursor"] = cursor

    request = TransactionsSyncRequest(**request_kwargs)

    response = client.transactions_sync(request)
    return {
        "added": response.get("added", []),
        "modified": response.get("modified", []),
        "removed": response.get("removed", []),
        "next_cursor": response.get("next_cursor"),
        "has_more": response.get("has_more", False),
    }
