"""Partial ad edits and stable budget-transfer keys."""

from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field, field_validator, model_validator

from .ad_creation import AdSchedule, Button, Money, Reference, StrictInput


def nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


IdempotencyKey = Annotated[
    str, Field(strict=True, min_length=1, max_length=128), AfterValidator(nonblank),
]
PositiveMoney = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]


class AdChanges(StrictInput):
    """Only supplied, non-null fields are changed; targeting is not editable."""

    title: str | None = Field(
        default=None, min_length=1, description="Internal title, at most 128 UTF-8 bytes.",
    )
    text: str | None = Field(default=None, min_length=1, max_length=160)
    promote_url: str | None = Field(default=None, min_length=1, max_length=256)
    cpm: PositiveMoney | None = None
    photo_id: Reference | None = Field(
        default=None, description="Replaces existing photo/video media.",
    )
    video_id: Reference | None = Field(
        default=None, description="Replaces existing photo/video media.",
    )
    impression_frequency: int | None = Field(default=None, ge=1, le=4)
    website_name: str | None = Field(default=None, min_length=1, max_length=40)
    website_photo_id: Reference | None = None
    button: Button | None = Field(
        default=None, description="Empty string restores the default website button.",
    )
    conversion_event_id: Reference | None = Field(
        default=None, description="Can only be set if not already set.",
    )
    additional_info: str | None = Field(
        default=None, max_length=64, description="Cannot be changed once set.",
    )
    show_userpic: bool | None = None
    daily_budget_limit: Money | None = Field(
        default=None, description="Zero removes the daily spending limit.",
    )
    is_paused: bool | None = Field(
        default=None,
        description=(
            "True pauses, false resumes; clears activation/deactivation dates "
            "unless new dates are supplied."
        ),
    )
    activate_date: int | None = Field(default=None, ge=0)
    deactivate_date: int | None = Field(default=None, ge=0)
    schedule: AdSchedule | Literal[False] | None = Field(
        default=None, description="A schedule object sets it; false removes it.",
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is not None:
            nonblank(value)
            if len(value.encode("utf-8")) > 128:
                raise ValueError("title must contain at most 128 UTF-8 bytes")
        return value

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        return nonblank(value) if value is not None else None

    @field_validator("promote_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            url = urlsplit(value)
            valid = url.scheme in {"http", "https", "tg"} and url.hostname
        except ValueError:
            valid = False
        if not valid or any(char.isspace() for char in value):
            raise ValueError("promote_url must be an absolute destination URL")
        return value

    @field_validator("schedule", mode="before")
    @classmethod
    def validate_schedule_type(cls, value: Any) -> Any:
        if (
            value is not None and value is not False
            and not isinstance(value, (dict, AdSchedule))
        ):
            raise ValueError("schedule must be an object or false to remove it")
        return value

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        if not self.model_dump(exclude_none=True):
            raise ValueError("changes must contain at least one non-null field")
        if self.photo_id is not None and self.video_id is not None:
            raise ValueError("photo_id and video_id are mutually exclusive")
        return self

    def client_params(self) -> dict[str, Any]:
        """Preserve explicit false, zero and empty strings; omit null fields."""
        params = self.model_dump(exclude_none=True, exclude={"schedule"})
        if isinstance(self.schedule, AdSchedule):
            params["schedule"] = self.schedule.to_telead()
        elif self.schedule is False:
            params["schedule"] = False
        return params
