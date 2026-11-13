"""Single-ad writes with explicit account scope and uncertain-outcome handling."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from telead import Client
from telead.errors import (
    APIError, RequestInProgressError, ServerError, TransportError, ValidationError,
)
from telead.models import Account, Ad

from ..errors import OperationError
from ..models.ad_management import AdChanges
from .accounts import resolve_account


@dataclass(frozen=True)
class AdChangeResult:
    account: Account
    outcome: Literal["succeeded", "failed", "unknown"]
    ad: Ad | None = None
    error: Exception | None = None


@dataclass(frozen=True)
class AdDeletionResult:
    account: Account
    outcome: Literal["succeeded", "failed", "unknown"]
    deleted: bool | None = None
    error: Exception | None = None


def change_ad(
    client: Client, *, ad_id: int,
    change: Callable[[str], Ad],
) -> AdChangeResult:
    """Resolve scope, then perform one write without rollback or follow-up writes.

    Lookup errors propagate before the write. Transport failures or malformed
    responses after attempting the write are retained as uncertain outcomes.
    """
    account = resolve_account(client)
    try:
        ad = change(account.account_id)
        if type(ad.raw.get("ad_id")) is not int or ad.ad_id != ad_id:
            raise OperationError("The write response did not contain the expected ad ID.")
    except (TransportError, ServerError, RequestInProgressError) as error:
        return AdChangeResult(account, "unknown", error=error)
    except (APIError, ValidationError) as error:
        return AdChangeResult(account, "failed", error=error)
    except Exception as error:
        return AdChangeResult(account, "unknown", error=error)
    return AdChangeResult(account, "succeeded", ad=ad)


def edit_ad(
    client: Client, *, ad_id: int, changes: AdChanges, return_target: bool,
) -> AdChangeResult:
    """Edit an ad and confirm a requested text change in the returned object."""
    result = change_ad(
        client, ad_id=ad_id,
        change=lambda scope: client.edit_ad(
            ad_id, **changes.client_params(), account_id=scope, return_target=return_target,
        ),
    )
    if (
        result.ad is not None and changes.text is not None
        and result.ad.raw.get("text") != changes.text
    ):
        return replace(result, outcome="unknown", error=OperationError(
            "Telegram Ads accepted editAd but the returned text does not match the request. "
            "The text change is unconfirmed. Inspect the ad with get_ads_by_id before retrying."
        ))
    return result


def delete_ad(client: Client, *, ad_id: int) -> AdDeletionResult:
    """Delete one ad, requiring confirmation from the API's Boolean result."""
    account = resolve_account(client)
    try:
        deleted = client.delete_ad(ad_id, account_id=account.account_id)
        if deleted is not True:
            raise OperationError("Telegram Ads did not confirm deletion. Check get_ads_by_id.")
    except (TransportError, ServerError, RequestInProgressError) as error:
        return AdDeletionResult(account, "unknown", error=error)
    except (APIError, ValidationError) as error:
        return AdDeletionResult(account, "failed", error=error)
    except Exception as error:
        return AdDeletionResult(account, "unknown", error=error)
    return AdDeletionResult(account, "succeeded", deleted=True)
