"""Public messages for failures detected by application operations."""

from collections.abc import Iterable

from telead.errors import APIError, TransportError, ValidationError


class OperationError(Exception):
    """A local operation failure whose message is safe to return to the caller."""


class ErrorMessages:
    """Format public errors without leaking credentials or response bodies."""

    def __init__(self, tokens: Iterable[str]) -> None:
        self._tokens = tuple(sorted(set(tokens) - {""}, key=len, reverse=True))

    def api_code(self, error: APIError) -> str:
        code = str(error.code)
        for token in self._tokens:
            code = code.replace(token, "[redacted]")
        return code[:128]

    def describe(self, error: Exception) -> str:
        if isinstance(error, OperationError):
            return str(error)
        if isinstance(error, ValidationError):
            return "TeleAd rejected the parameters; check the tool schema and API limits."
        if isinstance(error, APIError):
            return f"Telegram Ads API: {self.api_code(error)} (HTTP {error.status})."
        if isinstance(error, TransportError):
            return "Telegram Ads request failed or timed out; retry later."
        return "Unexpected failure during Telegram Ads operation."
