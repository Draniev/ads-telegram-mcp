"""Account discovery and balances."""

from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field
from telead import Client

from ..execution import TeleAdRunner
from ..profiles import ProfileResolver
from .common import READ_ONLY, AccountID, Offset, PageSize, Profile


def register(server: MCPServer, runner: TeleAdRunner, profiles: ProfileResolver) -> None:
    @server.tool(annotations=READ_ONLY.model_copy(update={"open_world_hint": False}))
    async def list_profiles() -> dict[str, Any]:
        """List configured Telegram Ads profile names and the effective default.

        Pick one name from profiles and pass it as a string in profile.
        Use default_profile when it is set and no profile was requested.
        A null default_profile with several names requires an explicit choice.
        Unnamed keys use numbered string labels such as "1" and "2".
        This tool returns no credentials and makes no API calls.
        """
        return {
            "profiles": list(profiles.names),
            "default_profile": profiles.default_profile,
        }

    @server.tool(annotations=READ_ONLY)
    async def get_current_account(profile: Profile | None = None) -> dict[str, Any]:
        """Get the token owner's account, balances and currency.

        Returns the selected profile's token owner regardless of its default
        related account. Use list_profiles to discover profile names.
        Available to ordinary advertisers and main/agency accounts.
        Retain the returned account_id, title and currency with this profile
        in conversation context and reuse the verified identity in later calls.
        """
        account = await runner.run(profiles.resolve(profile), Client.get_current_account)
        return account.raw

    @server.tool(annotations=READ_ONLY)
    async def list_related_accounts(
        offset: Offset = 0, limit: PageSize = 20, profile: Profile | None = None,
    ) -> dict[str, Any]:
        """Get one page of related accounts using a main/agency token only.

        Returns total_count and up to limit accounts. For the next page,
        increase the numeric offset by the number of accounts returned.
        Related accounts are scoped to the selected profile's token owner.
        An ordinary advertiser's token returns MAIN_ACCOUNT_REQUIRED: the API
        rejected this agency-only method. This is not a successful empty list.
        An empty accounts list on success means no related accounts on this page.
        For the token owner, use get_current_account. This error does not establish
        whether ad management or statistics methods are available.
        Retain discovered account IDs with this profile for later calls,
        keeping them separate from its token owner's account ID.
        """
        page = await runner.run(
            profiles.resolve(profile),
            lambda client: client.get_related_accounts_list(offset=offset, limit=limit),
        )
        return page.raw

    @server.tool(annotations=READ_ONLY)
    async def get_accounts_by_id(
        account_ids: Annotated[list[AccountID], Field(min_length=1, max_length=100)],
        profile: Profile | None = None,
    ) -> dict[str, Any]:
        """Get accounts by ID using a main/agency token only.

        Accepts 1 to 100 IDs accessible to the selected profile's token.
        Uses account_ids directly, regardless of the default related account.
        Requires a main/agency account, even when passing the token owner's ID.
        An ordinary advertiser's token returns MAIN_ACCOUNT_REQUIRED; supplying
        its own account ID does not make this agency-only method available.
        For the token owner, use get_current_account with the chosen profile.
        This error does not establish whether ad management or statistics
        methods are available.
        """
        accounts = await runner.run(
            profiles.resolve(profile), lambda client: client.get_accounts_by_id(account_ids),
        )
        return {"accounts": [account.raw for account in accounts]}
