"""Run typed synchronous operations with an owned TeleAd client off the MCP loop."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

import anyio
from mcp.server.mcpserver.exceptions import ToolError
from telead import Client

from .errors import ErrorMessages

T = TypeVar("T")


@dataclass(frozen=True)
class ClientConnection:
    """The token and account scope already selected for one operation."""

    token: str = field(repr=False)
    account_id: str | None = None


class TeleAdRunner:
    def __init__(self, errors: ErrorMessages) -> None:
        self.errors = errors

    async def run(self, connection: ClientConnection, operation: Callable[[Client], T]) -> T:
        """Run a synchronous operation with the supplied connection.

        The operation may make several calls and process their typed results
        using the same client. Materialize iterators before returning: the
        client is closed when the operation ends.
        """
        # requests is synchronous: keep I/O and retry backoff off the event loop.
        # Each operation owns its session; concurrent operations never share it.
        return await anyio.to_thread.run_sync(self._run, connection, operation)

    def _run(self, connection: ClientConnection, operation: Callable[[Client], T]) -> T:
        try:
            with Client(
                connection.token,
                account_id=connection.account_id,
                timeout=30.0,
                max_retries=1,
            ) as client:
                return operation(client)
        except ToolError:
            # A composed operation may deliberately report a domain error.
            raise
        except Exception as error:
            raise ToolError(self.errors.describe(error)) from None
