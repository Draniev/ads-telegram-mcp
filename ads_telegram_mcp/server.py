"""Composition root and stdio entry point (official MCP Python SDK v2)."""

from mcp.server import MCPServer

from . import __version__
from .config import Settings
from .execution import TeleAdRunner
from .tools import register_tools


def create_server(settings: Settings) -> MCPServer:
    server = MCPServer(
        "ads-telegram-mcp",
        version=__version__,
        log_level="WARNING",
        instructions=(
            "Telegram Ads tools for reading data, creating ads and uploading media. "
            "create_ads writes data unless dry_run=true; upload_media sends a local file. "
            "Creation may transfer budget, trigger review and enable delivery. "
            "Preserve per-ad idempotency keys when retrying within 24 hours.\n\n"
            "Account IDs are strings; ad IDs are "
            "integers scoped to an account.\n\n"
            "Omitted account_id uses TELEGRAM_ADS_ACCOUNT_ID "
            "if set, otherwise the token owner. get_current_account always returns the "
            "token owner.\n\n"
            "Times are Unix seconds; end times are exclusive. Preserve currency.\n\n"
            "List tools fetch one page; follow offsets explicitly.\n\n"
            "Use get_ads_stats for per-ad period totals: empty ad_ids selects all ads "
            "with automatic paging. Check complete and errors for partial failures."
        ),
    )
    runner = TeleAdRunner(settings)
    register_tools(server, runner)
    return server


def main() -> None:
    # stdout is exclusively the MCP transport. SDK logging goes to stderr.
    create_server(settings=Settings()).run(transport="stdio")
