"""Full targeting catalogues and channel/bot resolution in the token's scope."""

from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field

from ..execution import TeleAdRunner
from ..operations.targeting import (
    TargetCatalog,
    get_target_locations as fetch_locations,
    get_targeting_options as fetch_options,
)
from ..profiles import ProfileResolver
from .common import READ_ONLY, Profile

PeerRef = Annotated[int, Field(strict=True)] | Annotated[str, Field(min_length=1)]
CountryCode = Annotated[str, Field(pattern=r"^[A-Za-z]{2}$")]


def register(server: MCPServer, runner: TeleAdRunner, profiles: ProfileResolver) -> None:
    @server.tool(annotations=READ_ONLY)
    async def get_targeting_options(
        catalog: TargetCatalog,
        profile: Profile | None = None,
    ) -> dict[str, Any]:
        """Get a full catalogue of targeting languages, topics or countries.

        These three catalogues return every option without search or pagination.
        Returns catalog, options and total_count, with no next-page cursor.
        For locations, use get_target_locations separately when needed.

        Reuse catalogues already retrieved with this profile or saved work.
        Normally fetch them once and refresh no more than weekly, unless the user
        requests an update or the data appears stale.
        The server does not cache or save results.

        Use the returned language_code, topic_id or country_code
        in ad targeting. These API methods have no account_id parameter;
        the configured related-account default does not change their scope.
        """
        options = await runner.run(
            profiles.resolve(profile), lambda client: fetch_options(client, catalog=catalog),
        )
        return {
            "catalog": catalog,
            "options": [option.raw for option in options],
            "total_count": len(options),
        }

    @server.tool(annotations=READ_ONLY)
    async def get_target_locations(
        country_code: CountryCode,
        query: Annotated[str, Field(min_length=1)],
        profile: Profile | None = None,
    ) -> dict[str, Any]:
        """Search targeting locations within a country when needed.

        country_code is a two-letter country code; query must be nonblank.
        All pages of this search are retrieved automatically in one call.
        Returns locations and total_count, with no next-page cursor.
        Use location_id from the results in ad targeting.

        Reuse previous results for the same profile, country and query.
        The server does not cache or save results. The API method has no
        account_id parameter; the related-account default does not change scope.
        """
        locations = await runner.run(
            profiles.resolve(profile),
            lambda client: fetch_locations(client, country_code=country_code, query=query),
        )
        return {
            "locations": [location.raw for location in locations],
            "total_count": len(locations),
        }

    @server.tool(annotations=READ_ONLY)
    async def get_target_channel(
        channel_id: PeerRef,
        for_excluding: bool = False,
        profile: Profile | None = None,
    ) -> dict[str, Any]:
        """Resolve a channel for targeting by @username or numeric ID.

        Returns channel_id and, when available, title, username and photo_url.
        Numeric IDs require prior username resolution by the same account.
        Set for_excluding=true when resolving a channel for exclusion.

        This does not return subscribers, reach, CPM or performance statistics.
        The API method has no account_id parameter; resolution uses the token's
        account, regardless of the configured related-account default.
        """
        channel = await runner.run(
            profiles.resolve(profile),
            lambda client: client.get_target_channel(channel_id, for_excluding=for_excluding),
        )
        return channel.raw

    @server.tool(annotations=READ_ONLY)
    async def get_target_bot(bot_id: PeerRef, profile: Profile | None = None) -> dict[str, Any]:
        """Resolve a bot for targeting by @username or numeric ID.

        Returns bot_id and, when available, title, username and photo_url.
        Numeric IDs require prior username resolution by the same account.

        This does not return audience size, reach, CPM or performance statistics.
        The API method has no account_id parameter; resolution uses the token's
        account, regardless of the configured related-account default.
        """
        bot = await runner.run(
            profiles.resolve(profile), lambda client: client.get_target_bot(bot_id),
        )
        return bot.raw
