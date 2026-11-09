"""Single-ad writes with explicit account scope and uncertain-outcome handling."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from telead import Client
from telead.errors import (
    APIError, RequestInProgressError, ServerError, TransportError, ValidationError,
)
from telead.models import Account, Ad

from ..errors import OperationError
from .accounts import resolve_account


@dataclass(frozen=True)
class AdChangeResult:
    account: Account
    outcome: Literal["succeeded", "failed", "unknown"]
    ad: Ad | None = None
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
