"""Advertisement discovery and batch creation tools."""

from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field
from telead.errors import APIError

from ..execution import TeleAdRunner
from ..models.ad_creation import NewAd
from ..operations.ad_creation import create_ads as create_ads_operation
from ..profiles import ProfileResolver
from .common import CREATE_ADS, READ_ONLY, AccountID, PageSize, Profile


def register(server: MCPServer, runner: TeleAdRunner, profiles: ProfileResolver) -> None:
    @server.tool(annotations=CREATE_ADS)
    async def create_ads(
        ads: Annotated[list[NewAd], Field(min_length=1)],
        account_id: AccountID | None = None,
        dry_run: bool = False,
        stop_on_error: bool = True,
        profile: Profile | None = None,
    ) -> dict[str, Any]:
        """Create one or more ads in order, or validate them locally with dry_run.

        Defaults are zero initial budget and paused delivery. Positive budget
        transfers account funds and may trigger review. Activation/deactivation
        dates override is_paused. Amounts use the selected account's currency.

        Each ad requires an idempotency_key. Retry with the same key and identical
        parameters and profile within 24 hours; later retries may create another ad.
        Duplicates are not removed. No rollback is performed.

        Outcomes are succeeded, failed, unknown, or not_attempted. For unknown
        outcomes retry with the original key. stop_on_error defaults to true;
        authentication, permission and rate-limit errors always stop the batch.
        Unexpected client failures also stop remaining writes.

        dry_run makes no API calls and does not check access, budget or moderation.
        With multiple keys, omitted account_id uses the selected token owner.
        """
        connection = profiles.resolve(profile, account_id, require_token=not dry_run)
        if dry_run:
            return {
                "dry_run": True,
                "account_id": connection.account_id,
                "currency": None,
                "validated_count": len(ads),
                "ads": [item.model_dump(mode="json", exclude_none=True) for item in ads],
            }
        batch = await runner.run(
            connection, lambda client: create_ads_operation(client, ads, stop_on_error=stop_on_error),
        )
        results = []
        for result in batch.results:
            item = {
                "index": result.index, "idempotency_key": result.idempotency_key,
                "outcome": result.outcome,
            }
            if result.ad is not None:
                item["ad"] = {name: result.ad.raw.get(name) for name in (
                    "ad_id", "title", "status", "is_paused", "cpm", "remaining_budget",
                )}
                item["ad"]["currency"] = result.ad.currency or batch.account.currency
            if result.error is not None:
                item["error"] = {"message": runner.errors.describe(result.error)}
                if isinstance(result.error, APIError):
                    item["error"]["code"] = runner.errors.api_code(result.error)
            results.append(item)
        counts = {
            f"{outcome}_count": sum(item.outcome == outcome for item in batch.results)
            for outcome in ("succeeded", "failed", "unknown", "not_attempted")
        }
        return {
            "dry_run": False, "account_id": batch.account.account_id,
            "currency": batch.account.currency,
            "total_count": len(batch.results), **counts,
            "complete": counts["succeeded_count"] == len(batch.results),
            "results": results,
        }

    @server.tool(annotations=READ_ONLY)
    async def list_ads(
        account_id: AccountID | None = None,
        offset: str | None = None,
        limit: PageSize = 20,
        return_target: bool = False,
        profile: Profile | None = None,
    ) -> dict[str, Any]:
        """Get one page of ads from an account.

        For the next page, pass the returned next_offset unchanged as offset.
        This tool does not load additional pages automatically.
        Set return_target to include targeting settings.

        With multiple keys, omitted account_id uses the selected token owner.
        """
        page = await runner.run(
            profiles.resolve(profile, account_id),
            lambda client: client.get_ads_list(
                offset=offset, limit=limit, return_target=return_target,
            ),
        )
        return page.raw

    @server.tool(annotations=READ_ONLY)
    async def get_ads_by_id(
        ad_ids: Annotated[list[int], Field(min_length=1, max_length=100)],
        account_id: AccountID | None = None,
        return_target: bool = False,
        profile: Profile | None = None,
    ) -> dict[str, Any]:
        """Get selected ads by their IDs.

        Accepts 1 to 100 IDs. Ad IDs are unique within an account.
        Set return_target to include targeting settings.

        With multiple keys, omitted account_id uses the selected token owner.
        """
        ads = await runner.run(
            profiles.resolve(profile, account_id),
            lambda client: client.get_ads_by_id(ad_ids, return_target=return_target),
        )
        return {"ads": [ad.raw for ad in ads]}
