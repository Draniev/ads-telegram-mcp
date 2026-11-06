"""Advertisement discovery; mutations can be added as separate tools."""

from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field

from ..execution import TeleAdRunner
from .common import READ_ONLY, AccountID, PageSize


def register(server: MCPServer, runner: TeleAdRunner) -> None:
    @server.tool(annotations=READ_ONLY)
    async def list_ads(
        account_id: AccountID | None = None,
        offset: str | None = None,
        limit: PageSize = 20,
        return_target: bool = False,
    ) -> dict[str, Any]:
        """Get one page of ads. Reuse next_offset verbatim; no automatic paging. Omitted account_id uses env default or token owner."""
        page = await runner.run(
            lambda client: client.get_ads_list(
                account_id=account_id, offset=offset,
                limit=limit, return_target=return_target,
            )
        )
        return page.raw

    @server.tool(annotations=READ_ONLY)
    async def get_ads_by_id(
        ad_ids: Annotated[list[int], Field(min_length=1, max_length=100)],
        account_id: AccountID | None = None,
        return_target: bool = False,
    ) -> dict[str, Any]:
        """Get selected ads (up to 100); IDs are unique within an account. Set return_target for targeting details. Omitted account_id uses env default or token owner."""
        ads = await runner.run(
            lambda client: client.get_ads_by_id(
                ad_ids, account_id=account_id, return_target=return_target,
            )
        )
        return {"ads": [ad.raw for ad in ads]}
