"""Run typed synchronous operations with an owned TeleAd client off the MCP loop."""

from collections.abc import Callable
from typing import TypeVar

import anyio
from mcp.server.mcpserver.exceptions import ToolError
from telead import Client
from telead.errors import APIError, TransportError, ValidationError

from .config import Settings

T = TypeVar("T")


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
        except ValidationError:
            raise ToolError("TeleAd rejected the parameters; check the tool schema and API limits.") from None
        except APIError as error:
            # Do not forward response bodies, descriptions or transport messages:
            # they may contain request data. Preserve the API's machine error code.
            code = str(error.code).replace(self.settings.token, "[redacted]")[:128]
            raise ToolError(f"Telegram Ads API: {code} (HTTP {error.status}).") from None
        except TransportError:
            raise ToolError("Telegram Ads request failed or timed out; retry later.") from None
        except Exception:
            raise ToolError("Unexpected failure during Telegram Ads operation.") from None
