"""Creation inputs validated before any API calls or writes."""

from typing import Annotated, Any, Callable, ClassVar, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from telead.inputs import (
    InputAdSchedule,
    InputAdTarget,
    InputAdTargetBots,
    InputAdTargetChannels,
    InputAdTargetSearch,
    InputAdTargetUsers,
)
from telead.errors import ValidationError as TeleadValidationError

PeerRef = int | str
Placement = Literal["channel_post", "bot_banner", "search_result", "video_banner"]
Button = Literal[
    "", "subscribe", "view", "read", "learn_more", "download", "open",
    "sign_up", "buy", "order", "play", "try", "leave_request",
]
Money = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Reference = Annotated[str, Field(min_length=1)]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class TargetInput(StrictInput):
    _input_type: ClassVar[Callable[..., InputAdTarget]]

    def to_telead(self) -> InputAdTarget:
        """Build the corresponding typed TeleAd targeting input."""
        return self._input_type(**self.model_dump(exclude={"type"}))

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        try:
            self.to_telead().validate()
        except TeleadValidationError as error:
            raise ValueError(str(error)) from None
        return self


class ChannelsTarget(TargetInput):
    """Target channel placements by languages, topics or explicit channels."""

    _input_type = InputAdTargetChannels
    type: Literal["channels"]
    language_codes: list[str] = Field(default_factory=list, max_length=8)
    topic_ids: list[int] = Field(default_factory=list, max_length=20)
    exclude_topic_ids: list[int] = Field(default_factory=list, max_length=20)
    channel_ids: list[PeerRef] = Field(
        default_factory=list, max_length=100,
        description="Placement channels: @usernames or IDs previously resolved by this account.",
    )
    exclude_channel_ids: list[PeerRef] = Field(
        default_factory=list, max_length=100,
        description="Excluded placement channels: @usernames or previously resolved IDs.",
    )


class UsersTarget(TargetInput):
    """Target people by geography, language, interests, audiences and device."""

    _input_type = InputAdTargetUsers
    type: Literal["users"]
    country_codes: list[Annotated[str, Field(min_length=2, max_length=2)]] = Field(default_factory=list, max_length=8)
    location_ids: list[int] = Field(default_factory=list, max_length=20)
    language_codes: list[str] = Field(default_factory=list, max_length=8)
    topic_ids: list[int] = Field(default_factory=list, max_length=20)
    intersect_topics: bool = False
    exclude_topic_ids: list[int] = Field(default_factory=list, max_length=20)
    channel_ids: list[PeerRef] = Field(default_factory=list, max_length=100, description="Channel audiences to target, not placement channels.")
    exclude_channel_ids: list[PeerRef] = Field(default_factory=list, max_length=100, description="Channel audiences to exclude, not excluded placements.")
    audience_ids: list[int] = Field(default_factory=list, max_length=4)
    exclude_audience_ids: list[int] = Field(default_factory=list, max_length=4)
    device: Literal["ios", "android", "mobile", "desktop"] | None = None
    exclude_political_channels: bool = False
    political_channels_only: bool = False


class BotsTarget(TargetInput):
    """Target specific bots by username or previously resolved ID."""

    _input_type = InputAdTargetBots
    type: Literal["bots"]
    bot_ids: list[PeerRef] = Field(
        default_factory=list, max_length=100,
        description="Placement bots: @usernames or IDs previously resolved by this account.",
    )


class SearchTarget(TargetInput):
    """Target search queries; ad text is optional for this targeting type."""

    _input_type = InputAdTargetSearch
    type: Literal["search"]
    search_queries: list[str] = Field(min_length=1, max_length=10)


AdTarget = Annotated[
    ChannelsTarget | UsersTarget | BotsTarget | SearchTarget,
    Field(discriminator="type"),
]


class AdSchedule(StrictInput):
    """Seven hourly bitmasks, Monday first, using the API's timezone rules."""

    week_hours_mask: list[Annotated[int, Field(ge=0, le=16777215)]] = Field(
        min_length=7, max_length=7,
    )
    timezone: int | None = None
    use_viewer_timezone: bool = False

    def to_telead(self) -> InputAdSchedule:
        return InputAdSchedule(**self.model_dump())

    @model_validator(mode="after")
    def validate_schedule(self) -> Self:
        try:
            self.to_telead().validate()
        except TeleadValidationError as error:
            raise ValueError(str(error)) from None
        return self


class NewAd(StrictInput):
    """One creation request, including its stable API idempotency key."""

    title: str = Field(min_length=1, description="Internal title; at most 128 UTF-8 bytes.")
    promote_url: str = Field(min_length=1, max_length=256, description="Destination URL.")
    cpm: float = Field(gt=0, allow_inf_nan=False, description="Price per 1000 impressions in the account currency.")
    placement: Placement
    target: AdTarget
    idempotency_key: str = Field(min_length=1, max_length=128, description="Reuse with identical parameters for a retry within 24 hours.")
    text: str | None = Field(default=None, min_length=1, max_length=160)
    initial_budget: Money = Field(default=0, description="Transferred from the account; may trigger review when positive.")
    is_paused: bool = Field(default=True, description="Ignored by the API when activation or deactivation dates are supplied.")
    daily_budget_limit: Money | None = Field(default=None, description="Zero means no daily spending limit.")
    photo_id: Reference | None = None
    video_id: Reference | None = None
    show_userpic: bool | None = None
    impression_frequency: int | None = Field(default=None, ge=1, le=4)
    website_name: str | None = Field(default=None, min_length=1, max_length=40)
    website_photo_id: Reference | None = None
    button: Button | None = None
    conversion_event_id: Reference | None = None
    additional_info: str | None = Field(default=None, max_length=64)
    activate_date: int | None = Field(default=None, ge=0)
    deactivate_date: int | None = Field(default=None, ge=0)
    schedule: AdSchedule | None = None

    @field_validator("title")
    @classmethod
    def validate_title_bytes(cls, value: str) -> str:
        if not value.strip() or len(value.encode("utf-8")) > 128:
            raise ValueError("title must contain 1 to 128 UTF-8 bytes and not be blank")
        return value

    @field_validator("idempotency_key", "text")
    @classmethod
    def validate_nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value must not be blank")
        return value

    @model_validator(mode="after")
    def validate_combinations(self) -> Self:
        compatible = {
            "channels": {"channel_post"},
            "users": {"channel_post", "bot_banner", "video_banner"},
            "bots": {"bot_banner"},
            "search": {"search_result"},
        }
        if self.placement not in compatible[self.target.type]:
            raise ValueError("placement is incompatible with target.type")
        if self.target.type != "search" and self.text is None:
            raise ValueError("text is required unless target.type is search")
        if self.photo_id is not None and self.video_id is not None:
            raise ValueError("photo_id and video_id are mutually exclusive")
        if (self.photo_id or self.video_id) and self.target.type not in {"channels", "users"}:
            raise ValueError("photo/video media requires channels or users targeting")
        if self.schedule and self.schedule.use_viewer_timezone and self.target.type != "users":
            raise ValueError("use_viewer_timezone requires users targeting")
        try:
            url = urlsplit(self.promote_url)
            host = url.hostname
        except ValueError:
            raise ValueError("promote_url must be an absolute destination URL") from None
        if url.scheme not in {"http", "https", "tg"} or not host or any(c.isspace() for c in self.promote_url):
            raise ValueError("promote_url must be an absolute destination URL")
        telegram = url.scheme == "tg" or host.lower() in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}
        if not telegram and self.website_name is None:
            raise ValueError("website_name is required for an external destination")
        if telegram and any(value is not None for value in (
            self.website_name, self.website_photo_id, self.button, self.conversion_event_id,
        )):
            raise ValueError("website fields require an external destination")
        # Date eligibility belongs to the API. Local clock checks could reject
        # an identical idempotent retry after its scheduled time has passed.
        return self

    def client_params(self) -> dict[str, Any]:
        """Build parameters without changing the caller's key or targeting lists."""
        params = self.model_dump(exclude_none=True, exclude={"idempotency_key", "target", "schedule"})
        params["target"] = self.target.to_telead()
        if self.schedule is not None:
            params["schedule"] = self.schedule.to_telead()
        return params
