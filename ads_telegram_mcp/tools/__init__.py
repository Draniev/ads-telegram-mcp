"""Explicit domain registry; import and register new areas here."""

from mcp.server import MCPServer

from ..execution import TeleAdRunner
from . import accounts, ads, media, stats


def register_tools(server: MCPServer, runner: TeleAdRunner) -> None:
    for domain in (accounts, ads, stats, media):
        domain.register(server, runner)
