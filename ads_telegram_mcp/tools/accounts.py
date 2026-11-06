"""Account discovery and balances."""

from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field
from telead import Client

from ..execution import TeleAdRunner
from .common import READ_ONLY, AccountID, Offset, PageSize


def register(server: MCPServer, runner: TeleAdRunner) -> None:
    @server.tool(annotations=READ_ONLY)
    async def get_current_account() -> dict[str, Any]:
        """Get the token owner's account, balances and currency. Ignores the default related account."""
        account = await runner.run(Client.get_current_account)
        return account.raw

    @server.tool(annotations=READ_ONLY)
    async def list_related_accounts(
        offset: Offset = 0, limit: PageSize = 20,
    ) -> dict[str, Any]:
        """Get one page of related accounts. Advance numeric offset by returned count; total_count is included."""
        page = await runner.run(
            lambda client: client.get_related_accounts_list(offset=offset, limit=limit)
        )
        return page.raw

    @server.tool(annotations=READ_ONLY)
    async def get_accounts_by_id(
        account_ids: Annotated[list[AccountID], Field(min_length=1, max_length=100)],
    ) -> dict[str, Any]:
        """Get balances and currencies of specified accounts accessible to this token (up to 100 per call)."""
        accounts = await runner.run(lambda client: client.get_accounts_by_id(account_ids))
        return {"accounts": [account.raw for account in accounts]}
