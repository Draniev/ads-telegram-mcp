"""Process configuration. Credentials never appear in tool arguments."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TELEGRAM_ADS_",
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        str_strip_whitespace=True,
    )

    token: str = Field(default="", repr=False, exclude=True)
    account_id: str | None = None

    @field_validator("account_id")
    @classmethod
    def empty_account_is_none(cls, value: str | None) -> str | None:
        return value or None
