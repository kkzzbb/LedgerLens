"""DemoBank settings, read from environment variables only.

The application loads them when it starts (its lifespan). Other code reads
them through `get_settings()`. Nothing here reads a `.env` file: Docker
Compose (or `uv run --env-file`) puts the values in the process environment.

Each field is read from the environment variable with the field's name in
upper case (`demobank_api_key` from `DEMOBANK_API_KEY`). A value that is empty
or only whitespace counts as unset. No backend variable is read, except the
two telemetry variables both services share (`OTEL_ENABLED`,
`OTEL_EXPORTER_OTLP_ENDPOINT`).

`uv run python -m demobank.config` checks the configuration and prints
`Configuration OK`, or one line per problem on stderr with exit status 1.
"""

import os
import re
import sys
from datetime import date
from functools import lru_cache
from typing import Annotated, Any

from pydantic import (
    BeforeValidator,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.fields import FieldInfo
from pydantic_core import ErrorDetails, PydanticCustomError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from demobank.db.url import UnsupportedSchemeError, database_url

# Error types raised by the validators below. The line shown to the operator
# comes from `_problem()`, never from these messages.
_UNSUPPORTED_SCHEME = "unsupported_scheme"
_INVALID_URL = "invalid_url"
_NOT_SEED = "not_seed"
_NOT_DATE = "not_date"
_NOT_BOOLEAN = "not_boolean"
_OTLP_ENDPOINT_REQUIRED = "otlp_endpoint_required"

# ASCII digits only: `int()` would also take "+5", "1_000" or other digits.
_SEED = re.compile(r"[0-9]+", re.ASCII)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_BOOLEANS = {"true": True, "1": True, "false": False, "0": False}


class ConfigError(Exception):
    """The configuration is missing or invalid.

    The message has one line per problem. Each line names the environment
    variable and the reason, and never contains the value of any variable.
    """


def _parse_seed(value: Any) -> Any:
    if isinstance(value, str):
        if not _SEED.fullmatch(value.strip()):
            raise PydanticCustomError(_NOT_SEED, "not a non-negative integer")
        return int(value.strip())
    return value


def _parse_date(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        parsed: date | None = None
        if _DATE.fullmatch(text):
            try:
                parsed = date.fromisoformat(text)
            except ValueError:
                parsed = None
        if parsed is None:
            raise PydanticCustomError(_NOT_DATE, "not a YYYY-MM-DD date")
        return parsed
    return value


def _parse_bool(value: Any) -> Any:
    if isinstance(value, str):
        parsed = _BOOLEANS.get(value.strip().lower())
        if parsed is None:
            raise PydanticCustomError(_NOT_BOOLEAN, "not a boolean")
        return parsed
    return value


_Seed = Annotated[int, BeforeValidator(_parse_seed)]
_AnchorDate = Annotated[date | None, BeforeValidator(_parse_date)]
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
    """All DemoBank settings. Build it through `get_settings()`."""

    model_config = SettingsConfigDict(frozen=True, extra="forbid")

    # Required: the key every `/v1/*` request must send in `X-API-Key`.
    demobank_api_key: SecretStr

    # Required: the PostgreSQL database holding the `demobank_sim` schema (#9).
    # A secret: it embeds the database password.
    demobank_database_url: SecretStr
    # Optional: the seed and the last day of the generated history (#9). An
    # unset anchor date means "the date of first generation".
    demobank_seed: _Seed = 42
    demobank_anchor_date: _AnchorDate = None
    # Optional: telemetry (#122), shared with the backend. Export traces,
    # metrics and logs over OTLP/HTTP to this base URL; the endpoint is
    # required when OTEL_ENABLED is true.
    otel_enabled: _EnvBool = False
    otel_exporter_otlp_endpoint: str = ""

    @field_validator("demobank_database_url")
    @classmethod
    def _postgres_url(cls, url: SecretStr) -> SecretStr:
        kind = None
        try:
            database_url(url.get_secret_value())
        except UnsupportedSchemeError:
            kind = _UNSUPPORTED_SCHEME
        except ValueError:
            kind = _INVALID_URL
        # Raised outside the `except` block so nothing holding the URL is chained.
        if kind is not None:
            raise PydanticCustomError(kind, "invalid database URL")
        return url

    @model_validator(mode="after")
    def _otlp_endpoint_when_enabled(self) -> "Settings":
        if self.otel_enabled and not self.otel_exporter_otlp_endpoint.strip():
            raise PydanticCustomError(_OTLP_ENDPOINT_REQUIRED, "endpoint required")
        return self

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


def _problem(error: ErrorDetails) -> str:
    """One line for one validation error, built without the offending value."""
    kind = error["type"]
    if kind == _OTLP_ENDPOINT_REQUIRED:
        return "OTEL_EXPORTER_OTLP_ENDPOINT is required when OTEL_ENABLED is true"
    name = env_name(str(error["loc"][0])) if error["loc"] else "Configuration"
    if kind == "missing":
        return f"{name} is required but not set (an empty or blank value counts as unset)"
    if kind == _UNSUPPORTED_SCHEME:
        return f"{name} has an unsupported scheme; expected postgresql://"
    if kind == _NOT_SEED:
        return f"{name} must be a non-negative integer"
    if kind == _NOT_DATE:
        return f"{name} must be a date in YYYY-MM-DD format"
    if kind == _NOT_BOOLEAN:
        return f"{name} must be true, false, 1 or 0"
    return f"{name} has an invalid value"


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
