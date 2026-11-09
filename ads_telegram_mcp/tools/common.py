"""Shared schema constraints and MCP metadata."""

from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from ..config import ProfileName

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)

CREATE_ADS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)

UPLOAD_MEDIA = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)

WRITE_AD = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)

AccountID = Annotated[str, Field(min_length=1)]
Profile = Annotated[
    ProfileName,
    Field(description="One profile name or numbered label from list_profiles, as a string."),
]
PageSize = Annotated[int, Field(ge=1, le=100)]
Offset = Annotated[int, Field(ge=0)]
