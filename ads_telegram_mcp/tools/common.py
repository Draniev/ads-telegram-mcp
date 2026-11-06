"""Shared schema constraints and MCP metadata."""

from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)

AccountID = Annotated[str, Field(min_length=1)]
PageSize = Annotated[int, Field(ge=1, le=100)]
Offset = Annotated[int, Field(ge=0)]
