"""Resolve a concrete account before a write operation."""

from telead import Client
from telead.models import Account

from ..errors import OperationError


def resolve_account(client: Client) -> Account:
    """Look up the scoped account or token owner before a write."""
    scope = client.account_id
    account = client.get_current_account()
    if scope is not None and scope != account.account_id:
        accounts = client.get_accounts_by_id([scope])
        account = next((item for item in accounts if item.account_id == scope), None)
        if account is None:
            raise OperationError("The selected account is not accessible to this token.")
    if not account.account_id or account.currency not in {"EUR", "TON", "XTR"}:
        raise OperationError("The API did not return a valid account ID and currency.")
    return account
