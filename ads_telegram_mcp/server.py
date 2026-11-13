"""Composition root and stdio entry point (official MCP Python SDK v2)."""

from mcp.server import MCPServer
from pydantic import ValidationError
from pydantic_settings import SettingsError

from . import __version__
from .config import Settings
from .errors import ErrorMessages
from .execution import TeleAdRunner
from .profiles import ProfileResolver
from .tools import register_tools


def create_server(settings: Settings) -> MCPServer:
    server = MCPServer(
        "ads-telegram-mcp",
        version=__version__,
        log_level="WARNING",
        instructions=(
            'Pass one profile per API call as a string, e.g. {"profile":"agency"}. '
            "Use the exact requested name or numbered label from list_profiles. "
            "If several profiles are available and the request leaves the choice unclear, "
            "ask which to use. With one profile, it can be omitted. Keep the same profile "
            "across related calls. Use separate calls only for profiles the user requests. "
            "Never pass a list or an API key as profile.\n\n"
            "Token and name arrays are server configuration in .env. list_profiles returns "
            "labels for selection. If MCP fails to start because of invalid configuration, "
            "report the startup error and ask the user to correct .env and restart the server. "
            "Do not read, convert, or reuse the token list to bypass the MCP connection.\n\n"
            "Telegram Ads tools for reading data, creating and editing ads, "
            "funding ads, submitting them for review and uploading media. "
            "create_ads writes data unless dry_run=true; upload_media sends a local file. "
            "Creation may transfer budget, trigger review and enable delivery. "
            "Preserve the profile and per-ad idempotency keys when retrying within 24 hours.\n\n"
            "increase_ad_budget and decrease_ad_budget transfer an amount for one ad. "
            "Preserve the profile, parameters and idempotency key on retries within 24 hours. "
            "For unknown write outcomes inspect the ad before further actions. "
            "edit_ad and submit_ad_for_review also write one ad at a time.\n\n"
            "For text edits, check outcome and the returned ad.text. Telegram may accept "
            "editAd while leaving the text unchanged; that returns outcome=unknown. "
            "delete_ad deletes one ad. Return remaining budget with "
            "decrease_ad_budget first when needed, then delete only the requested ad.\n\n"
            "Account IDs are strings; ad IDs are "
            "integers scoped to an account.\n\n"
            "Omitted account_id uses the selected token's owner, or the configured "
            "related-account default in single-token mode. get_current_account "
            "always returns the token owner. "
            "Targeting catalogues and resolvers use profile but have no account_id.\n\n"
            "Times are Unix seconds; end times are exclusive. Preserve currency.\n\n"
            "list_ads and list_related_accounts fetch one page; follow offsets explicitly.\n\n"
            "get_targeting_options returns full language, topic or country catalogues. "
            "Reuse previously retrieved catalogues for the same profile; "
            "normally refresh no more than weekly unless the user requests an update "
            "or the data appears stale. The server does not cache or save them.\n\n"
            "Use get_target_locations only when location targeting is needed; "
            "it retrieves all search results for a country and query.\n\n"
            "Use get_ads_stats for per-ad period totals: empty ad_ids selects all ads "
            "with automatic paging. Check complete and errors for partial failures."
        ),
    )
    runner = TeleAdRunner(ErrorMessages((settings.token, *settings.configured_tokens)))
    register_tools(server, runner, ProfileResolver(settings))
    return server


def main() -> None:
    # stdout is exclusively the MCP transport. SDK logging goes to stderr.
    try:
        settings = Settings()
    except (SettingsError, ValidationError):
        raise SystemExit(
            "Invalid Telegram Ads configuration. In .env, set TELEGRAM_ADS_TOKENS "
            'to a JSON array of strings, e.g. ["token_1", "token_2"]. '
            'If set, TELEGRAM_ADS_TOKEN_NAMES must be a JSON array with one unique name '
            'per token, e.g. ["personal", "agency"]. Correct the configuration and restart MCP.'
        ) from None
    create_server(settings=settings).run(transport="stdio")
