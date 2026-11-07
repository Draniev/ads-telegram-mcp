"""Explicit domain registry; import and register new areas here."""

from mcp.server import MCPServer

from ..execution import TeleAdRunner
from . import accounts, ad_management, ads, media, stats, targeting


def register_tools(server: MCPServer, runner: TeleAdRunner) -> None:
    for domain in (accounts, ads, ad_management, stats, media, targeting):
        domain.register(server, runner)
