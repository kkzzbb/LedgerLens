"""Typed configuration, read from environment variables only.

The API and the worker call `load_settings_or_exit()` when they start. Other
code reads the settings through `get_settings()`. Nothing here reads a `.env`
file: Docker Compose (or `uv run --env-file`) puts the values in the process
environment.

Each field is read from the environment variable with the field's name in
upper case (`database_url` from `DATABASE_URL`). A value that is empty or only
whitespace counts as unset.

`uv run python -m ledgerlens.config` checks the configuration and prints
`Configuration OK`, or one line per problem on stderr with exit status 1.
"""

import os
import re
import sys
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Any

from pydantic import (
    BeforeValidator,
    Field,
    SecretStr,
    ValidationError,
)
from pydantic.fields import FieldInfo
from pydantic_core import ErrorDetails, PydanticCustomError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

_INTEGER = re.compile(r"[+-]?[0-9]+")
_BOOLEANS = {"true": True, "1": True, "false": False, "0": False}

# Error types raised by the validators below. The reason shown to the operator
# comes from `_reason()`, never from these messages.
_NOT_INTEGER = "not_integer"
_NOT_BOOLEAN = "not_boolean"


class ConfigError(Exception):
    """The configuration is missing or invalid.

    The message has one line per problem. Each line names the environment
    variable and the reason, and never contains the value of any variable.
    """


def _parse_int(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if _INTEGER.fullmatch(text) is None:
            raise PydanticCustomError(_NOT_INTEGER, "not an integer")
        return int(text)
    return value


def _parse_bool(value: Any) -> Any:
    if isinstance(value, str):
        parsed = _BOOLEANS.get(value.strip().lower())
        if parsed is None:
            raise PydanticCustomError(_NOT_BOOLEAN, "not a boolean")
        return parsed
    return value


_EnvInt = Annotated[int, BeforeValidator(_parse_int)]
_PositiveInt = Annotated[_EnvInt, Field(ge=1)]
_EnvBool = Annotated[bool, BeforeValidator(_parse_bool)]


def env_name(field_name: str) -> str:
    """The environment variable a `Settings` field is read from."""
    return field_name.upper()


class _EnvironmentSource(PydanticBaseSettingsSource):
    """Reads each field from the process environment, treating blank as unset."""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        value = os.environ.get(env_name(field_name))
        if value is not None and not value.strip():
            value = None
        return value, field_name, False

    def __call__(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for field_name, field in self.settings_cls.model_fields.items():
            value, key, _ = self.get_field_value(field, field_name)
            if value is not None:
                values[key] = value
        return values


class Settings(BaseSettings):
    """All backend settings. Build it through `get_settings()`."""

    model_config = SettingsConfigDict(frozen=True, extra="forbid")

    # Required
    database_url: SecretStr  # a secret: it embeds the database password
    demobank_api_key: SecretStr

    # Optional, with demo defaults
    demobank_base_url: str = "http://demobank:8100"
    demo_mode: _EnvBool = True
    sync_interval_seconds: _PositiveInt = 120
    sync_page_size: Annotated[_EnvInt, Field(ge=1, le=500)] = 100
    stale_threshold_minutes: _PositiveInt = 30
    failure_streak_threshold: _PositiveInt = 3
    anthropic_api_key: SecretStr = SecretStr("")
    agent_model: str = "claude-opus-5-5"
    otel_exporter_otlp_endpoint: str = ""
    # Anomaly rules evaluate only the debits booked in the last N calendar days
    anomaly_evaluation_window_days: _PositiveInt = 7
    # Most days between two payments flagged as a possible duplicate
    anomaly_duplicate_window_days: Annotated[_EnvInt, Field(ge=0)] = 3
    # Largest amount difference of a possible duplicate, in % of the larger amount
    anomaly_duplicate_amount_tolerance_percent: Annotated[Decimal, Field(ge=0, le=100)] = Decimal(
        "1"
    )

    @property
    def agents_enabled(self) -> bool:
        """True only when `ANTHROPIC_API_KEY` is set to a non-blank value."""
        return bool(self.anthropic_api_key.get_secret_value().strip())

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # The process environment is the only source: no `.env` file, no
        # secrets directory, no constructor arguments.
        return (_EnvironmentSource(settings_cls),)


def _reason(error: ErrorDetails) -> str:
    """A reason for one validation error, built without the offending value."""
    kind = error["type"]
    context = error.get("ctx", {})
    if kind == "missing":
        return "is required but not set (an empty or blank value counts as unset)"
    if kind == _NOT_INTEGER:
        return "must be a whole number"
    if kind == _NOT_BOOLEAN:
        return "must be true, false, 1 or 0"
    if kind == "greater_than_equal":
        return f"must be at least {context['ge']}"
    if kind == "less_than_equal":
        return f"must be at most {context['le']}"
    return "has an invalid value"


def _problem(error: ErrorDetails) -> str:
    """One line for one validation error: the variable name, then the reason."""
    name = env_name(str(error["loc"][0])) if error["loc"] else "Configuration"
    return f"{name} {_reason(error)}"


def _load() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        lines = [_problem(error) for error in exc.errors(include_input=False)]
    # Raised outside the `except` block so that the ValidationError, which
    # holds the input values, is not chained to the ConfigError.
    raise ConfigError("\n".join(lines))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The settings, built once and cached until `get_settings.cache_clear()`.

    Raises `ConfigError` when the configuration is missing or invalid.
    """
    return _load()


def load_settings_or_exit() -> Settings:
    """The settings, or the problems on stderr and exit status 1 (no traceback)."""
    try:
        return get_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    load_settings_or_exit()
    print("Configuration OK")
