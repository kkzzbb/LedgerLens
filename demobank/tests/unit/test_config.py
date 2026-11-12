import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from demobank.config import (
    ConfigError,
    Settings,
    env_name,
    get_settings,
    load_settings_or_exit,
)

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"
DEMOBANK_DIR = Path(__file__).resolve().parents[2]

ALL_VARIABLES = [env_name(field) for field in Settings.model_fields]
API_KEY_MARKER = "MARKER-demobank-api-key"
ADMIN_KEY_MARKER = "MARKER-demobank-admin-key"

MISSING_API_KEY = (
    "DEMOBANK_API_KEY is required but not set (an empty or blank value counts as unset)"
)
ADMIN_ENABLED_INVALID = "DEMOBANK_ADMIN_ENABLED must be true, false, 1 or 0"
ADMIN_KEY_REQUIRED = "DEMOBANK_ADMIN_KEY is required when DEMOBANK_ADMIN_ENABLED is true"
ADMIN_KEY_EQUAL = "DEMOBANK_ADMIN_KEY must differ from DEMOBANK_API_KEY"

# Backend variables (#4). DemoBank must ignore them.
BACKEND_VARIABLES = {
    "DATABASE_URL": "MARKER-database-url",
    "DEMOBANK_BASE_URL": "MARKER-base-url",
    "DEMO_MODE": "MARKER-demo-mode",
    "SYNC_INTERVAL_SECONDS": "MARKER-interval",
    "ANTHROPIC_API_KEY": "MARKER-anthropic-key",
}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No settings variable is set and nothing is cached, before and after."""
    for name in ALL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def error_lines(monkeypatch: pytest.MonkeyPatch, **variables: str) -> list[str]:
    """Sets the variables and returns the lines of the resulting ConfigError."""
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError) as caught:
        get_settings()
    return str(caught.value).splitlines()


# Fields, defaults and overrides


def test_field_names_cover_the_documented_variables() -> None:
    assert ALL_VARIABLES == [
        "DEMOBANK_API_KEY",
        "DEMOBANK_ADMIN_ENABLED",
        "DEMOBANK_ADMIN_KEY",
    ]


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")

    settings = get_settings()

    assert settings.demobank_api_key.get_secret_value() == "test-api-key"
    assert settings.demobank_admin_enabled is False
    assert settings.demobank_admin_key.get_secret_value() == ""


def test_overrides_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "other-api-key")
    monkeypatch.setenv("DEMOBANK_ADMIN_ENABLED", "true")
    monkeypatch.setenv("DEMOBANK_ADMIN_KEY", "other-admin-key")

    settings = get_settings()

    assert settings.demobank_api_key.get_secret_value() == "other-api-key"
    assert settings.demobank_admin_enabled is True
    assert settings.demobank_admin_key.get_secret_value() == "other-admin-key"


def test_backend_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in BACKEND_VARIABLES.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")

    settings = get_settings()

    assert set(Settings.model_fields).isdisjoint(name.lower() for name in BACKEND_VARIABLES)
    assert "MARKER" not in repr(settings.model_dump())


def test_backend_variables_alone_are_not_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = error_lines(monkeypatch, **BACKEND_VARIABLES)

    assert lines == [MISSING_API_KEY]


# Caching and sources


def test_get_settings_is_cached_until_cache_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "first")
    first = get_settings()
    monkeypatch.setenv("DEMOBANK_API_KEY", "second")

    assert get_settings() is first
    get_settings.cache_clear()
    assert get_settings().demobank_api_key.get_secret_value() == "second"


def test_env_file_in_the_working_directory_is_not_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("DEMOBANK_API_KEY=from-dotenv\n")
    monkeypatch.chdir(tmp_path)

    assert error_lines(monkeypatch) == [MISSING_API_KEY]


def test_constructor_arguments_are_not_a_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")

    settings = Settings(demobank_admin_enabled=True)

    assert settings.demobank_admin_enabled is False


# DEMOBANK_API_KEY


@pytest.mark.parametrize("blank", [None, "", "   ", "\t\n"], ids=["unset", "empty", "spaces", "ws"])
def test_api_key_unset_or_blank(monkeypatch: pytest.MonkeyPatch, blank: str | None) -> None:
    variables = {} if blank is None else {"DEMOBANK_API_KEY": blank}

    assert error_lines(monkeypatch, **variables) == [MISSING_API_KEY]


# DEMOBANK_ADMIN_ENABLED


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        ("True", True),
        ("1", True),
        ("false", False),
        ("FALSE", False),
        ("fAlSe", False),
        ("0", False),
    ],
)
def test_admin_enabled_accepts_booleans_in_any_case(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")
    monkeypatch.setenv("DEMOBANK_ADMIN_KEY", "test-admin-key")
    monkeypatch.setenv("DEMOBANK_ADMIN_ENABLED", value)

    assert get_settings().demobank_admin_enabled is expected


@pytest.mark.parametrize("value", ["yes", "no", "maybe", "2", "truee"])
def test_admin_enabled_that_is_not_a_boolean_is_invalid(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    lines = error_lines(monkeypatch, DEMOBANK_API_KEY="test-api-key", DEMOBANK_ADMIN_ENABLED=value)

    assert lines == [ADMIN_ENABLED_INVALID]


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_admin_enabled_gives_the_default(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")
    monkeypatch.setenv("DEMOBANK_ADMIN_ENABLED", blank)

    assert get_settings().demobank_admin_enabled is False


# DEMOBANK_ADMIN_KEY


@pytest.mark.parametrize("blank", [None, "", "   "], ids=["unset", "empty", "spaces"])
def test_admin_enabled_without_admin_key_is_invalid(
    monkeypatch: pytest.MonkeyPatch, blank: str | None
) -> None:
    variables = {"DEMOBANK_API_KEY": "test-api-key", "DEMOBANK_ADMIN_ENABLED": "true"}
    if blank is not None:
        variables["DEMOBANK_ADMIN_KEY"] = blank

    assert error_lines(monkeypatch, **variables) == [ADMIN_KEY_REQUIRED]


def test_admin_enabled_with_admin_key_equal_to_api_key_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = error_lines(
        monkeypatch,
        DEMOBANK_API_KEY="same-key",
        DEMOBANK_ADMIN_ENABLED="1",
        DEMOBANK_ADMIN_KEY="same-key",
    )

    assert lines == [ADMIN_KEY_EQUAL]


@pytest.mark.parametrize("admin_key", [None, "", "test-api-key"], ids=["unset", "empty", "equal"])
def test_admin_disabled_accepts_an_empty_or_equal_admin_key(
    monkeypatch: pytest.MonkeyPatch, admin_key: str | None
) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")
    monkeypatch.setenv("DEMOBANK_ADMIN_ENABLED", "false")
    if admin_key is not None:
        monkeypatch.setenv("DEMOBANK_ADMIN_KEY", admin_key)

    settings = get_settings()

    assert settings.demobank_admin_enabled is False


def test_all_problems_are_reported_one_per_line(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = error_lines(monkeypatch, DEMOBANK_ADMIN_ENABLED="true")

    assert lines == [MISSING_API_KEY, ADMIN_KEY_REQUIRED]


# Secrets never shown


def test_repr_and_str_do_not_contain_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", API_KEY_MARKER)
    monkeypatch.setenv("DEMOBANK_ADMIN_ENABLED", "true")
    monkeypatch.setenv("DEMOBANK_ADMIN_KEY", ADMIN_KEY_MARKER)

    settings = get_settings()

    assert "MARKER" not in repr(settings)
    assert "MARKER" not in str(settings)


@pytest.mark.parametrize(
    "variables",
    [
        {"DEMOBANK_API_KEY": "   ", "DEMOBANK_ADMIN_KEY": ADMIN_KEY_MARKER},
        {
            "DEMOBANK_API_KEY": API_KEY_MARKER,
            "DEMOBANK_ADMIN_ENABLED": "MARKER-yes",
            "DEMOBANK_ADMIN_KEY": ADMIN_KEY_MARKER,
        },
        {"DEMOBANK_API_KEY": API_KEY_MARKER, "DEMOBANK_ADMIN_ENABLED": "true"},
        {
            "DEMOBANK_API_KEY": API_KEY_MARKER,
            "DEMOBANK_ADMIN_ENABLED": "true",
            "DEMOBANK_ADMIN_KEY": API_KEY_MARKER,
        },
    ],
    ids=["api-key-blank", "admin-enabled-invalid", "admin-key-missing", "admin-key-equal"],
)
def test_config_error_never_contains_a_value(
    monkeypatch: pytest.MonkeyPatch, variables: dict[str, str]
) -> None:
    for name, value in variables.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ConfigError) as caught:
        get_settings()

    shown = f"{caught.value}\n{caught.value!r}\n{caught.value.args!r}"
    assert "MARKER" not in shown
    # Nothing that holds the input values is chained to the error.
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


# load_settings_or_exit and `python -m demobank.config`


def test_load_settings_or_exit_returns_valid_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")

    assert load_settings_or_exit() is get_settings()


def test_load_settings_or_exit_prints_the_problems_and_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        load_settings_or_exit()

    captured = capsys.readouterr()
    assert caught.value.code == 1
    assert captured.out == ""
    assert captured.err == f"{MISSING_API_KEY}\n"


def run_module(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Runs `python -m demobank.config` with exactly the given environment."""
    return subprocess.run(
        [sys.executable, "-m", "demobank.config"],
        cwd=DEMOBANK_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "environment",
    [
        {"DEMOBANK_API_KEY": API_KEY_MARKER},
        {
            "DEMOBANK_API_KEY": API_KEY_MARKER,
            "DEMOBANK_ADMIN_ENABLED": "true",
            "DEMOBANK_ADMIN_KEY": ADMIN_KEY_MARKER,
        },
        {
            "DEMOBANK_API_KEY": API_KEY_MARKER,
            "DEMOBANK_ADMIN_ENABLED": "false",
            "DEMOBANK_ADMIN_KEY": API_KEY_MARKER,
        },
    ],
    ids=["api-key-only", "admin-enabled", "admin-disabled-equal-key"],
)
def test_module_prints_configuration_ok(environment: dict[str, str]) -> None:
    result = run_module(environment)

    assert result.returncode == 0
    assert result.stdout == "Configuration OK\n"
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({"DEMOBANK_ADMIN_KEY": ADMIN_KEY_MARKER}, MISSING_API_KEY),
        ({"DEMOBANK_API_KEY": " ", "DEMOBANK_ADMIN_KEY": ADMIN_KEY_MARKER}, MISSING_API_KEY),
        (
            {
                "DEMOBANK_API_KEY": API_KEY_MARKER,
                "DEMOBANK_ADMIN_ENABLED": "yes",
                "DEMOBANK_ADMIN_KEY": ADMIN_KEY_MARKER,
            },
            ADMIN_ENABLED_INVALID,
        ),
        (
            {"DEMOBANK_API_KEY": API_KEY_MARKER, "DEMOBANK_ADMIN_ENABLED": "true"},
            ADMIN_KEY_REQUIRED,
        ),
        (
            {
                "DEMOBANK_API_KEY": API_KEY_MARKER,
                "DEMOBANK_ADMIN_ENABLED": "true",
                "DEMOBANK_ADMIN_KEY": "  ",
            },
            ADMIN_KEY_REQUIRED,
        ),
        (
            {
                "DEMOBANK_API_KEY": API_KEY_MARKER,
                "DEMOBANK_ADMIN_ENABLED": "TRUE",
                "DEMOBANK_ADMIN_KEY": API_KEY_MARKER,
            },
            ADMIN_KEY_EQUAL,
        ),
    ],
    ids=[
        "api-key-unset",
        "api-key-blank",
        "admin-enabled-yes",
        "admin-key-unset",
        "admin-key-blank",
        "admin-key-equal",
    ],
)
def test_module_prints_the_problem_without_traceback_or_value(
    environment: dict[str, str], expected: str
) -> None:
    result = run_module(environment)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"{expected}\n"
    assert "Traceback" not in result.stderr
    assert "MARKER" not in result.stdout + result.stderr


# .env.example


def env_example_values() -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in ENV_EXAMPLE.read_text().splitlines()
        if line and not line.startswith("#")
    )


def test_env_example_has_a_line_for_every_demobank_variable() -> None:
    lines = ENV_EXAMPLE.read_text().splitlines()

    missing = [
        name for name in ALL_VARIABLES if not any(line.startswith(f"{name}=") for line in lines)
    ]

    assert missing == []


def test_env_example_carries_the_defaults_of_the_optional_variables() -> None:
    values = env_example_values()

    for field, info in Settings.model_fields.items():
        if info.is_required():
            continue
        default = info.default
        if hasattr(default, "get_secret_value"):
            default = default.get_secret_value()
        expected = str(default).lower() if isinstance(default, bool) else str(default)
        assert values[env_name(field)] == expected

    assert values["DEMOBANK_ADMIN_ENABLED"] == "false"
    assert values["DEMOBANK_ADMIN_KEY"] == ""
