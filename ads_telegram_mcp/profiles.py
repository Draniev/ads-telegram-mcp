"""Resolve local profile names and account scope before running API operations."""

from mcp.server.mcpserver.exceptions import ToolError

from .config import Settings
from .execution import ClientConnection


class ProfileResolver:
    def __init__(self, settings: Settings) -> None:
        self.names = settings.profile_names
        self.default_profile = settings.effective_default_profile
        self._tokens = dict(zip(self.names, settings.configured_tokens, strict=True))
        self._account_id = settings.account_id if len(self.names) <= 1 else None

    def resolve(
        self, profile: str | None, account_id: str | None = None, *, require_token: bool = True,
    ) -> ClientConnection:
        """Choose a token and account locally; None account_id means the token owner."""
        name = profile if profile is not None else self.default_profile
        if name is not None:
            token = self._tokens.get(name)
            if token is None:
                raise ToolError("Unknown Telegram Ads profile. Use list_profiles to see available names.")
        elif self.names:
            raise ToolError("Specify a profile when multiple tokens are configured. See list_profiles.")
        elif require_token:
            raise ToolError("Set TELEGRAM_ADS_TOKENS in the MCP server environment.")
        else:
            token = ""
        return ClientConnection(token, account_id if account_id is not None else self._account_id)
