"""
Plaid API service layer.
Handles all interactions with the Plaid API.
"""

from django.conf import settings
from plaid.api import plaid_api
from plaid.configuration import Configuration
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.transactions_sync_request import TransactionsSyncRequest


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


def create_link_token(user_id: str, client_name: str = "Koala Budget"):
    """
    Create a Plaid Link token for initializing Plaid Link.

    Args:
        user_id: Unique identifier for the user
        client_name: Name to display in Plaid Link

    Returns:
        Link token string
    """
    client = get_plaid_client()

    request = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id=str(user_id)),
        client_name=client_name,
        products=[Products("transactions")],
        country_codes=[CountryCode("US")],
        language="en",
    )

    response = client.link_token_create(request)
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
        country_codes=[CountryCode("US")],
    )

    response = client.institutions_get_by_id(request)
    return response["institution"]


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

