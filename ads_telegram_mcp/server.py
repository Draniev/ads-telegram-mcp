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
            "Read-only Telegram Ads API tools. Account IDs are strings; ad IDs are "
            "integers scoped to an account. Omitted account_id uses TELEGRAM_ADS_ACCOUNT_ID "
            "if set, otherwise the token owner. get_current_account always returns the "
            "token owner. Times are Unix seconds; end times are exclusive. Preserve currency. "
            "List tools fetch one page; follow offsets explicitly."
        ),
    )
    runner = TeleAdRunner(settings)
    register_tools(server, runner)
    return server


def main() -> None:
    # stdout is exclusively the MCP transport. SDK logging goes to stderr.
    create_server(settings=Settings()).run(transport="stdio")
