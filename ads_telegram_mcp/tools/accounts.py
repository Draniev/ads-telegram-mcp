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
        """Get the token owner's account, balances and currency.

        Always returns the token owner, regardless of the default related account.
        """
        account = await runner.run(Client.get_current_account)
        return account.raw

    @server.tool(annotations=READ_ONLY)
    async def list_related_accounts(
        offset: Offset = 0, limit: PageSize = 20,
    ) -> dict[str, Any]:
        """Get one page of the token owner's related accounts.

        Returns total_count and up to limit accounts. For the next page,
        increase the numeric offset by the number of accounts returned.
        """
        page = await runner.run(
            lambda client: client.get_related_accounts_list(offset=offset, limit=limit)
        )
        return page.raw

    @server.tool(annotations=READ_ONLY)
    async def get_accounts_by_id(
        account_ids: Annotated[list[AccountID], Field(min_length=1, max_length=100)],
    ) -> dict[str, Any]:
        """Get balances and currencies for the specified account IDs.

        Accepts 1 to 100 IDs of accounts accessible to this token.
        Uses account_ids directly, regardless of the default related account.
        """
        accounts = await runner.run(lambda client: client.get_accounts_by_id(account_ids))
        return {"accounts": [account.raw for account in accounts]}
