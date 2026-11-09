"""Create a batch in order, preserving successful and uncertain outcomes."""

from dataclasses import dataclass, field
from typing import Literal

from telead import Client
from telead.errors import (
    APIError, AuthenticationError, PermissionDeniedError, RateLimitError,
    RequestInProgressError, ServerError, TransportError, ValidationError,
)
from telead.models import Account, Ad

from ..errors import OperationError
from ..models.ad_creation import NewAd
from .accounts import resolve_account

Outcome = Literal["succeeded", "failed", "unknown", "not_attempted"]


@dataclass(frozen=True)
class CreationResult:
    index: int
    idempotency_key: str
    outcome: Outcome
    ad: Ad | None = None
    error: Exception | None = None


@dataclass
class CreationBatch:
    account: Account
    results: list[CreationResult] = field(default_factory=list)


def create_ads(
    client: Client, ads: list[NewAd], *,
    stop_on_error: bool,
) -> CreationBatch:
    """Resolve the account, then create each ad with its caller-supplied key.

    API rejection is failed; an uncertain response is unknown. Stopping leaves
    remaining items not_attempted. No created ad is rolled back or deleted.
    """
    batch = CreationBatch(account=resolve_account(client))
    stopped = False
    for index, item in enumerate(ads):
        if stopped:
            batch.results.append(CreationResult(index, item.idempotency_key, "not_attempted"))
            continue
        try:
            ad = client.create_ad(
                **item.client_params(), account_id=batch.account.account_id,
                idempotency_key=item.idempotency_key,
            )
            if not isinstance(ad.raw.get("ad_id"), int) or isinstance(ad.raw["ad_id"], bool):
                raise OperationError("The creation response did not contain a valid ad ID.")
        except (AuthenticationError, PermissionDeniedError, RateLimitError) as error:
            batch.results.append(CreationResult(index, item.idempotency_key, "failed", error=error))
            stopped = True
        except (TransportError, ServerError, RequestInProgressError) as error:
            batch.results.append(CreationResult(index, item.idempotency_key, "unknown", error=error))
            stopped = stop_on_error
        except (APIError, ValidationError) as error:
            batch.results.append(CreationResult(index, item.idempotency_key, "failed", error=error))
            stopped = stop_on_error
        except Exception as error:
            batch.results.append(CreationResult(index, item.idempotency_key, "unknown", error=error))
            stopped = True
        else:
            batch.results.append(CreationResult(index, item.idempotency_key, "succeeded", ad=ad))
    return batch
