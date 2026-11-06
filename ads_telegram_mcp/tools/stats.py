"""Account/ad time series and monthly per-ad reports."""

from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..execution import TeleAdRunner
from .common import READ_ONLY, AccountID

Timestamp = Annotated[int, Field(ge=0)]
Interval = Literal[300, 86400]


def validate_period(start: int, end: int, interval: int) -> None:
    if end <= start or end - start > 1000 * interval:
        raise ToolError("Use from_time < to_time and a period of at most 1000 intervals.")


def register(server: MCPServer, runner: TeleAdRunner) -> None:
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
