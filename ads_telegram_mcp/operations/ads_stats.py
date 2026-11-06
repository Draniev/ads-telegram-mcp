"""Collect and aggregate per-ad statistics using one TeleAd client."""

from dataclasses import dataclass, field
from decimal import Decimal

from telead import Client
from telead.errors import (
    APIError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
    TeleadError,
    TransportError,
)
from telead.models import AdStatItem


class AdsPaginationError(Exception):
    """The ads list could not be traversed completely."""


@dataclass(frozen=True)
class AdTotals:
    """Period totals in a single currency, with decimal spending arithmetic."""

    currency: str | None
    views: int
    opens: int
    clicks: int
    actions: int
    spent_budget: Decimal


@dataclass(frozen=True)
class AdStats:
    """One ad's totals and optional original interval rows."""

    ad_id: int
    data_points: int
    totals: AdTotals | None
    points: list[AdStatItem] | None


@dataclass(frozen=True)
class AdStatsFailure:
    """An ad-specific failure retained for safe reporting at the MCP boundary."""

    ad_id: int
    error: TeleadError


@dataclass
class AdsStatsBatch:
    """Results and individual failures for a set of unique ad IDs."""

    total_count: int
    ads: list[AdStats] = field(default_factory=list)
    errors: list[AdStatsFailure] = field(default_factory=list)


def _all_ad_ids(client: Client, account_id: str | None) -> list[int]:
    """Load all ad IDs, raising AdsPaginationError if pagination stalls."""
    ids: dict[int, None] = {}
    offset: str | None = None
    seen_offsets: set[str] = set()
    while True:
        page = client.get_ads_list(
            account_id=account_id, offset=offset, limit=100, return_target=False,
        )
        ids.update((ad.ad_id, None) for ad in page.ads)
        offset = page.next_offset
        if not offset:
            return list(ids)
        if not page.ads or offset in seen_offsets:
            raise AdsPaginationError(
                "Cannot get all ads: the API returned an empty page with a next cursor "
                "or repeated a pagination cursor."
            )
        seen_offsets.add(offset)


def _totals(points: list[AdStatItem]) -> AdTotals | None:
    """Sum one ad's interval rows; return None when no data was returned."""
    if not points:
        return None
    currencies = {point.currency for point in points}
    if len(currencies) != 1:
        raise ValueError("Cannot aggregate statistics in different currencies.")
    return AdTotals(
        currency=points[0].currency,
        views=sum(point.views for point in points),
        opens=sum(point.opens for point in points),
        clicks=sum(point.clicks for point in points),
        actions=sum(point.actions for point in points),
        spent_budget=sum((Decimal(str(point.spent_budget)) for point in points), Decimal(0)),
    )


def collect_ads_stats(
    client: Client,
    *,
    from_time: int,
    to_time: int,
    interval: int,
    ad_ids: list[int] | None = None,
    account_id: str | None = None,
    include_timeseries: bool = False,
) -> AdsStatsBatch:
    """Collect per-ad statistics using the caller's open client.

    Empty or omitted ad_ids loads all ads. Duplicate IDs are processed once.
    Individual API and transport failures are retained in the result;
    authentication, permission and rate-limit failures stop the operation.

    Preserve interval rows only when include_timeseries is true.
    The caller must supply a validated, interval-aligned period.
    """
    ids = list(dict.fromkeys(ad_ids)) if ad_ids else _all_ad_ids(client, account_id)
    batch = AdsStatsBatch(total_count=len(ids))
    for ad_id in ids:
        try:
            points = client.get_ad_stats(
                ad_id, from_time, to_time, interval=interval, account_id=account_id,
            )
        except (AuthenticationError, PermissionDeniedError, RateLimitError):
            # These affect the whole operation. Stop rather than repeating the
            # same rejection for every remaining ad after TeleAd's own retries.
            raise
        except (APIError, TransportError) as error:
            batch.errors.append(AdStatsFailure(ad_id=ad_id, error=error))
            continue
        batch.ads.append(AdStats(
            ad_id=ad_id,
            data_points=len(points),
            totals=_totals(points),
            points=points if include_timeseries else None,
        ))
    return batch
