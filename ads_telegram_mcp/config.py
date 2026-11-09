"""Process configuration. Credentials never appear in tool arguments."""

from pathlib import Path
from typing import Annotated, Self

from pydantic import Field, StringConstraints, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

NonblankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ProfileName = NonblankString


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TELEGRAM_ADS_",
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    token: str = Field(default="", repr=False, exclude=True)
    tokens: tuple[NonblankString, ...] | None = Field(default=None, repr=False, exclude=True)
    token_names: tuple[ProfileName, ...] | None = None
    account_id: str | None = None

    @field_validator("account_id")
    @classmethod
    def empty_account_is_none(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def validate_token_names(self) -> Self:
        if self.token_names is not None:
            if len(self.token_names) != len(self.configured_tokens):
                raise ValueError("TELEGRAM_ADS_TOKEN_NAMES must contain one name per token")
            if len(set(self.token_names)) != len(self.token_names):
                raise ValueError("TELEGRAM_ADS_TOKEN_NAMES must contain unique names")
        return self

    @property
    def configured_tokens(self) -> tuple[str, ...]:
        if self.tokens is not None:
            return self.tokens
        return (self.token,) if self.token else ()

    @property
    def profile_names(self) -> tuple[str, ...]:
        if self.token_names is not None:
            return self.token_names
        return tuple(str(i) for i in range(1, len(self.configured_tokens) + 1))

    @property
    def effective_default_profile(self) -> str | None:
        names = self.profile_names
        return names[0] if len(names) == 1 else None
