"""Resolve a concrete account before a write operation."""

from telead import Client
from telead.models import Account

from ..errors import OperationError


def resolve_account(client: Client, account_id: str | None) -> Account:
    """Resolve an explicit scope, client default, or token owner exactly once."""
    scope = account_id if account_id is not None else client.account_id
    if scope is None:
        account = client.get_current_account()
    else:
        accounts = client.get_accounts_by_id([scope])
        account = next((item for item in accounts if item.account_id == scope), None)
        if account is None:
            raise OperationError("The selected account is not accessible to this token.")
    if not account.account_id or account.currency not in {"EUR", "TON", "XTR"}:
        raise OperationError("The API did not return a valid account ID and currency.")
    return account
