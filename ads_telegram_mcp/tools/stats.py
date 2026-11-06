"""Account/ad time series and monthly per-ad reports."""

from dataclasses import asdict
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from telead import Client

from ..execution import TeleAdRunner, public_error_message
from ..operations.ads_stats import AdsPaginationError, AdsStatsBatch, collect_ads_stats
from .common import READ_ONLY, AccountID

Timestamp = Annotated[int, Field(ge=0)]
Interval = Literal[300, 86400]


def validate_period(start: int, end: int, interval: int) -> None:
    if end <= start or end - start > 1000 * interval:
        raise ToolError("Use from_time < to_time and a period of at most 1000 intervals.")


def register(server: MCPServer, runner: TeleAdRunner) -> None:
    @server.tool(annotations=READ_ONLY)
    async def get_ads_stats(
        from_time: Timestamp, to_time: Timestamp,
        ad_ids: list[int] | None = None,
        interval: Interval = 86400,
        account_id: AccountID | None = None,
        include_timeseries: bool = False,
    ) -> dict[str, Any]:
        """Get per-ad totals for [from_time, to_time), in Unix seconds.

        The period must not exceed 1000 intervals.

        Empty or omitted ad_ids selects all ads via automatic paging,
        regardless of status. Duplicate IDs are processed once.
        Set include_timeseries to include interval rows.

        Returns rounded bounds, per-ad totals, counts, complete and errors.
        Totals are null when no data is available. Check complete and errors
        before treating the result as complete.

        Omitted account_id uses TELEGRAM_ADS_ACCOUNT_ID if set,
        otherwise the token owner's account.
        """
        validate_period(from_time, to_time, interval)
        start = from_time // interval * interval
        end = to_time // interval * interval
        validate_period(start, end, interval)

        def collect(client: Client) -> AdsStatsBatch:
            try:
                return collect_ads_stats(
                    client, from_time=start, to_time=end, interval=interval,
                    ad_ids=ad_ids, account_id=account_id,
                    include_timeseries=include_timeseries,
                )
            except AdsPaginationError as error:
                raise ToolError(str(error)) from None

        batch = await runner.run(collect)
        ads = []
        for result in batch.ads:
            totals = None
            if result.totals is not None:
                totals = asdict(result.totals)
                totals["spent_budget"] = float(result.totals.spent_budget)
            item = {"ad_id": result.ad_id, "data_points": result.data_points, "totals": totals}
            if result.points is not None:
                item["stats"] = [point.raw for point in result.points]
            ads.append(item)
        return {
            "from_time": start, "to_time": end, "interval": interval,
            "total_count": batch.total_count,
            "succeeded_count": len(batch.ads), "failed_count": len(batch.errors),
            "complete": not batch.errors,
            "ads": ads,
            "errors": [
                {"ad_id": failure.ad_id,
                 "error": public_error_message(failure.error, runner.settings.token)}
                for failure in batch.errors
            ],
        }

    @server.tool(annotations=READ_ONLY)
    async def get_account_stats(
        from_time: Timestamp, to_time: Timestamp,
        interval: Interval = 86400, account_id: AccountID | None = None,
    ) -> dict[str, Any]:
        """Get account time series in [from_time, to_time), Unix seconds. API rounds to interval starts; max 1000 intervals. Money uses returned currency. Omitted account_id uses env default or token owner."""
        validate_period(from_time, to_time, interval)
        stats = await runner.run(
            lambda client: client.get_account_stats(
                from_time, to_time, interval=interval, account_id=account_id,
            )
        )
        return {"stats": [point.raw for point in stats]}

    @server.tool(annotations=READ_ONLY)
    async def get_ad_stats(
        ad_id: int, from_time: Timestamp, to_time: Timestamp,
        interval: Interval = 86400, account_id: AccountID | None = None,
    ) -> dict[str, Any]:
        """Get one ad's time series in [from_time, to_time), Unix seconds. API rounds to interval starts; max 1000 intervals. Omitted account_id uses env default or token owner."""
        validate_period(from_time, to_time, interval)
        stats = await runner.run(
            lambda client: client.get_ad_stats(
                ad_id, from_time, to_time, interval=interval, account_id=account_id,
            )
        )
        return {"stats": [point.raw for point in stats]}

    @server.tool(annotations=READ_ONLY)
    async def get_account_report(
        year: Annotated[int, Field(ge=2021, le=2100)],
        month: Annotated[int, Field(ge=1, le=12)],
        account_id: AccountID | None = None,
    ) -> dict[str, Any]:
        """Get monthly totals per active ad; monetary values use each item's currency. Omitted account_id uses env default or token owner."""
        report = await runner.run(
            lambda client: client.get_account_report(year, month, account_id=account_id)
        )
        return {"report": [item.raw for item in report]}
