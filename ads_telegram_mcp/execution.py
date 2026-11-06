"""Run typed synchronous operations with an owned TeleAd client off the MCP loop."""

from collections.abc import Callable
from typing import TypeVar

import anyio
from mcp.server.mcpserver.exceptions import ToolError
from telead import Client
from telead.errors import APIError, TransportError, ValidationError

from .config import Settings

T = TypeVar("T")


def public_error_message(error: Exception, token: str) -> str:
    """Describe a failure without forwarding response bodies or request data."""
    if isinstance(error, ValidationError):
        return "TeleAd rejected the parameters; check the tool schema and API limits."
    if isinstance(error, APIError):
        code = str(error.code).replace(token, "[redacted]")[:128] if token else str(error.code)[:128]
        return f"Telegram Ads API: {code} (HTTP {error.status})."
    if isinstance(error, TransportError):
        return "Telegram Ads request failed or timed out; retry later."
    return "Unexpected failure during Telegram Ads operation."


class TeleAdRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def run(self, operation: Callable[[Client], T]) -> T:
        """Run a synchronous operation; preserve its return type and value.

        The operation may make several calls and process their typed results
        using the same client. Materialize iterators before returning: the
        client is closed when the operation ends.
        """
        # requests is synchronous: keep I/O and retry backoff off the event loop.
        # Each operation owns its session; concurrent operations never share it.
        return await anyio.to_thread.run_sync(self._run, operation)

    def _run(self, operation: Callable[[Client], T]) -> T:
        if not self.settings.token:
            raise ToolError("Set TELEGRAM_ADS_TOKEN in the MCP server environment.")
        try:
            with Client(
                self.settings.token,
                account_id=self.settings.account_id,
                timeout=30.0,
                max_retries=1,
            ) as client:
                return operation(client)
        except ToolError:
            # A composed operation may deliberately report a domain error.
            raise
        except Exception as error:
            raise ToolError(public_error_message(error, self.settings.token)) from None
