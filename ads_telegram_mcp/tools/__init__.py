"""Explicit domain registry; import and register new areas here."""

from mcp.server import MCPServer

from ..execution import TeleAdRunner
from . import accounts, ads, stats


def register_tools(server: MCPServer, runner: TeleAdRunner) -> None:
    for domain in (accounts, ads, stats):
        domain.register(server, runner)
