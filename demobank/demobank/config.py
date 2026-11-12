"""DemoBank settings, read from environment variables only.

The application loads them when it starts (its lifespan). Other code reads
them through `get_settings()`. Nothing here reads a `.env` file: Docker
Compose (or `uv run --env-file`) puts the values in the process environment.

Each field is read from the environment variable with the field's name in
upper case (`demobank_api_key` from `DEMOBANK_API_KEY`). A value that is empty
or only whitespace counts as unset. No backend variable is read.

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
    Field,
    SecretStr,
    ValidationError,
    ValidationInfo,
    field_validator,
)
from pydantic.fields import FieldInfo
from pydantic_core import ErrorDetails, PydanticCustomError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from demobank.db.url import UnsupportedSchemeError, database_url

_BOOLEANS = {"true": True, "1": True, "false": False, "0": False}

# Error types raised by the validators below. The line shown to the operator
# comes from `_problem()`, never from these messages.
_NOT_BOOLEAN = "not_boolean"
_ADMIN_KEY_MISSING = "admin_key_missing"
_ADMIN_KEY_EQUALS_API_KEY = "admin_key_equals_api_key"
_UNSUPPORTED_SCHEME = "unsupported_scheme"
_INVALID_URL = "invalid_url"
_NOT_SEED = "not_seed"
_NOT_DATE = "not_date"

# ASCII digits only: `int()` would also take "+5", "1_000" or other digits.
_SEED = re.compile(r"[0-9]+", re.ASCII)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)


class ConfigError(Exception):
    """The configuration is missing or invalid.

    The message has one line per problem. Each line names the environment
    variable and the reason, and never contains the value of any variable.
    """


def _parse_bool(value: Any) -> Any:
    if isinstance(value, str):
        parsed = _BOOLEANS.get(value.strip().lower())
        if parsed is None:
            raise PydanticCustomError(_NOT_BOOLEAN, "not a boolean")
        return parsed
    return value


_EnvBool = Annotated[bool, BeforeValidator(_parse_bool)]


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


_Seed = Annotated[int, BeforeValidator(_parse_seed)]
_AnchorDate = Annotated[date | None, BeforeValidator(_parse_date)]


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

    # Optional. The admin routes (#12) need their own key when enabled.
    demobank_admin_enabled: _EnvBool = False
    # Validated even when unset, so a missing key is caught when admin is on.
    demobank_admin_key: SecretStr = Field(default=SecretStr(""), validate_default=True)

    # Required: the PostgreSQL database holding the `demobank_sim` schema (#9).
    # A secret: it embeds the database password.
    demobank_database_url: SecretStr
    # Optional: the seed and the last day of the generated history (#9). An
    # unset anchor date means "the date of first generation".
    demobank_seed: _Seed = 42
    demobank_anchor_date: _AnchorDate = None

    @field_validator("demobank_admin_key")
    @classmethod
    def _admin_key_when_enabled(cls, admin_key: SecretStr, info: ValidationInfo) -> SecretStr:
        # The fields above are declared first, so they are already validated.
        # A field that is itself invalid is absent from `info.data` and is
        # reported on its own.
        if info.data.get("demobank_admin_enabled") is not True:
            return admin_key
        value = admin_key.get_secret_value()
        if not value.strip():
            raise PydanticCustomError(_ADMIN_KEY_MISSING, "admin key missing")
        api_key = info.data.get("demobank_api_key")
        if api_key is not None and value == api_key.get_secret_value():
            raise PydanticCustomError(_ADMIN_KEY_EQUALS_API_KEY, "admin key equals API key")
        return admin_key

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
    if kind == _ADMIN_KEY_MISSING:
        return "DEMOBANK_ADMIN_KEY is required when DEMOBANK_ADMIN_ENABLED is true"
    if kind == _ADMIN_KEY_EQUALS_API_KEY:
        return "DEMOBANK_ADMIN_KEY must differ from DEMOBANK_API_KEY"
    name = env_name(str(error["loc"][0])) if error["loc"] else "Configuration"
    if kind == "missing":
        return f"{name} is required but not set (an empty or blank value counts as unset)"
    if kind == _NOT_BOOLEAN:
        return f"{name} must be true, false, 1 or 0"
    if kind == _UNSUPPORTED_SCHEME:
        return f"{name} has an unsupported scheme; expected postgresql://"
    if kind == _NOT_SEED:
        return f"{name} must be a non-negative integer"
    if kind == _NOT_DATE:
        return f"{name} must be a date in YYYY-MM-DD format"
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
