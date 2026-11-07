"""Budget top-ups, partial edits and review submission for one ad at a time."""

from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field
from telead.errors import APIError

from ..execution import TeleAdRunner, api_error_code, public_error_message
from ..models.ad_management import AdChanges, IdempotencyKey, PositiveMoney
from ..operations.ad_management import AdChangeResult, change_ad
from .common import WRITE_AD, AccountID

AdID = Annotated[int, Field(strict=True)]


def _response(
    result: AdChangeResult, *, ad_id: int, token: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Serialize at the MCP boundary, retaining API fields and safe errors."""
    response: dict[str, Any] = {
        "account_id": result.account.account_id,
        "ad_id": ad_id,
        "currency": result.account.currency,
        "outcome": result.outcome,
    }
    if idempotency_key is not None:
        response["idempotency_key"] = idempotency_key
    if result.ad is not None:
        response["ad"] = result.ad.raw
    if result.error is not None:
        message = public_error_message(result.error, token)
        if result.outcome == "unknown":
            message = "The write outcome is unknown; inspect the ad before further actions."
        response["error"] = {"message": message}
        if isinstance(result.error, APIError):
            response["error"]["code"] = api_error_code(result.error, token)
    return response


def register(server: MCPServer, runner: TeleAdRunner) -> None:
    @server.tool(annotations=WRITE_AD)
    async def increase_ad_budget(
        ad_id: AdID,
        amount: PositiveMoney,
        idempotency_key: IdempotencyKey,
        account_id: AccountID | None = None,
        return_target: bool = False,
    ) -> dict[str, Any]:
        """Transfer funds from the account to one existing ad's budget.

        amount is a positive increment, not the desired final balance, in the
        selected account's currency. Funding can enable delivery of an ad.
        This does not change its pause state or explicitly submit it for review.

        Supply a stable idempotency_key. Retry only with the same key and all
        parameters within 24 hours; a new key or later retry may fund it again.
        Returns account_id, currency, outcome, idempotency_key and ad or error.
        For outcome=unknown, preserve the original key; never retry with a new one.

        return_target includes targeting in the returned ad.
        Omitted account_id uses the configured default or the token owner.
        """
        result = await runner.run(lambda client: change_ad(
            client, account_id=account_id, ad_id=ad_id,
            change=lambda scope: client.increase_ad_budget(
                ad_id, amount, account_id=scope, idempotency_key=idempotency_key,
                return_target=return_target,
            ),
        ))
        return _response(
            result, ad_id=ad_id, token=runner.settings.token,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=WRITE_AD)
    async def edit_ad(
        ad_id: AdID,
        changes: AdChanges,
        account_id: AccountID | None = None,
        return_target: bool = False,
    ) -> dict[str, Any]:
        """Edit only the supplied fields of one ad, including pause or resume.

        changes must have at least one non-null field. Omitted/null fields stay
        unchanged. Targeting and placement cannot be edited with this method.
        is_paused=true pauses; false resumes and can enable spending. Pause state
        changes clear activation/deactivation dates unless new dates are supplied;
        supplied dates override is_paused according to API rules.

        daily_budget_limit=0 removes the cap; schedule=false removes the schedule.
        A new photo_id or video_id replaces existing media. conversion_event_id
        and additional_info cannot be changed once set. Editing a funded ad may
        trigger review. Currency, access and state-dependent limits are API checks.

        Returns account_id, currency, outcome and ad or error. For outcome=unknown,
        inspect get_ads_by_id before deciding whether to repeat the edit.
        return_target includes targeting. Omitted account_id uses the configured
        default or the token owner.
        """
        result = await runner.run(lambda client: change_ad(
            client, account_id=account_id, ad_id=ad_id,
            change=lambda scope: client.edit_ad(
                ad_id, **changes.client_params(), account_id=scope,
                return_target=return_target,
            ),
        ))
        return _response(result, ad_id=ad_id, token=runner.settings.token)

    @server.tool(annotations=WRITE_AD)
    async def submit_ad_for_review(
        ad_id: AdID,
        account_id: AccountID | None = None,
        return_target: bool = False,
    ) -> dict[str, Any]:
        """Explicitly submit one ad with status ready_for_review for moderation.

        Use only when the ad needs submission; creating or editing a funded ad
        may already submit it automatically. This call does not add budget or
        change pause state. Approval can enable delivery if other conditions allow.

        Returns account_id, currency, outcome and ad or error. This API method has
        no idempotency key. For outcome=unknown, inspect get_ads_by_id and the ad's
        status before retrying; the first request may already have been applied.
        return_target includes targeting. Omitted account_id uses the configured
        default or the token owner.
        """
        result = await runner.run(lambda client: change_ad(
            client, account_id=account_id, ad_id=ad_id,
            change=lambda scope: client.submit_ad_for_review(
                ad_id, account_id=scope, return_target=return_target,
            ),
        ))
        return _response(result, ad_id=ad_id, token=runner.settings.token)
