import subprocess
import sys
from collections.abc import Iterator
from datetime import date
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

MISSING_API_KEY = (
    "DEMOBANK_API_KEY is required but not set (an empty or blank value counts as unset)"
)

# A valid DEMOBANK_DATABASE_URL, set by `clean_environment` unless a test
# removes it. Checking the settings never connects to it.
DATABASE_URL = "postgresql://ledgerlens:ledgerlens@db:5432/ledgerlens"
PASSWORD_MARKER = "MARKERdbpassword"
MISSING_DATABASE_URL = (
    "DEMOBANK_DATABASE_URL is required but not set (an empty or blank value counts as unset)"
)
UNSUPPORTED_SCHEME = "DEMOBANK_DATABASE_URL has an unsupported scheme; expected postgresql://"
INVALID_SEED = "DEMOBANK_SEED must be a non-negative integer"
INVALID_ANCHOR_DATE = "DEMOBANK_ANCHOR_DATE must be a date in YYYY-MM-DD format"

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
    """Only a valid DEMOBANK_DATABASE_URL is set, and nothing is cached, before and after."""
    for name in ALL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEMOBANK_DATABASE_URL", DATABASE_URL)
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
        "DEMOBANK_DATABASE_URL",
        "DEMOBANK_SEED",
        "DEMOBANK_ANCHOR_DATE",
    ]


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")

    settings = get_settings()

    assert settings.demobank_api_key.get_secret_value() == "test-api-key"
    assert settings.demobank_database_url.get_secret_value() == DATABASE_URL
    assert settings.demobank_seed == 42
    assert settings.demobank_anchor_date is None


def test_overrides_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "other-api-key")
    monkeypatch.setenv("DEMOBANK_SEED", "1234")
    monkeypatch.setenv("DEMOBANK_ANCHOR_DATE", "2024-02-29")

    settings = get_settings()

    assert settings.demobank_api_key.get_secret_value() == "other-api-key"
    assert settings.demobank_seed == 1234
    assert settings.demobank_anchor_date == date(2024, 2, 29)


def test_backend_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in BACKEND_VARIABLES.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")

    settings = get_settings()

    assert set(Settings.model_fields).isdisjoint(name.lower() for name in BACKEND_VARIABLES)
    assert "MARKER" not in repr(settings.model_dump())


def test_backend_variables_alone_are_not_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    # DATABASE_URL (the backend's) does not stand in for DEMOBANK_DATABASE_URL.
    monkeypatch.delenv("DEMOBANK_DATABASE_URL")

    lines = error_lines(monkeypatch, **BACKEND_VARIABLES)

    assert lines == [MISSING_API_KEY, MISSING_DATABASE_URL]


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

    settings = Settings(demobank_seed=7)

    assert settings.demobank_seed == 42


# DEMOBANK_API_KEY


@pytest.mark.parametrize("blank", [None, "", "   ", "\t\n"], ids=["unset", "empty", "spaces", "ws"])
def test_api_key_unset_or_blank(monkeypatch: pytest.MonkeyPatch, blank: str | None) -> None:
    variables = {} if blank is None else {"DEMOBANK_API_KEY": blank}

    assert error_lines(monkeypatch, **variables) == [MISSING_API_KEY]


def test_all_problems_are_reported_one_per_line(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = error_lines(monkeypatch, DEMOBANK_SEED="-1")

    assert lines == [MISSING_API_KEY, INVALID_SEED]


# Secrets never shown


def test_repr_and_str_do_not_contain_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", API_KEY_MARKER)

    settings = get_settings()

    assert "MARKER" not in repr(settings)
    assert "MARKER" not in str(settings)


@pytest.mark.parametrize(
    "variables",
    [
        {"DEMOBANK_API_KEY": "   ", "DEMOBANK_SEED": "MARKER-seed"},
        {"DEMOBANK_API_KEY": API_KEY_MARKER, "DEMOBANK_ANCHOR_DATE": "MARKER-date"},
    ],
    ids=["api-key-blank", "anchor-date-invalid"],
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
    """Runs `python -m demobank.config` with exactly the given environment, plus a
    valid DEMOBANK_DATABASE_URL unless the environment sets that one."""
    return subprocess.run(
        [sys.executable, "-m", "demobank.config"],
        cwd=DEMOBANK_DIR,
        env={"DEMOBANK_DATABASE_URL": DATABASE_URL, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "environment",
    [
        {"DEMOBANK_API_KEY": API_KEY_MARKER},
        {"DEMOBANK_API_KEY": API_KEY_MARKER, "DEMOBANK_SEED": "7"},
    ],
    ids=["api-key-only", "with-seed"],
)
def test_module_prints_configuration_ok(environment: dict[str, str]) -> None:
    result = run_module(environment)

    assert result.returncode == 0
    assert result.stdout == "Configuration OK\n"
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({}, MISSING_API_KEY),
        ({"DEMOBANK_API_KEY": " "}, MISSING_API_KEY),
    ],
    ids=["api-key-unset", "api-key-blank"],
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
        if default is None:
            default = ""
        expected = str(default).lower() if isinstance(default, bool) else str(default)
        assert values[env_name(field)] == expected


def test_env_example_has_the_demobank_database_lines_with_a_comment() -> None:
    lines = ENV_EXAMPLE.read_text().splitlines()
    values = env_example_values()

    assert values["DEMOBANK_DATABASE_URL"] == DATABASE_URL
    assert values["DEMOBANK_SEED"] == "42"
    assert values["DEMOBANK_ANCHOR_DATE"] == ""
    for name in ("DEMOBANK_DATABASE_URL", "DEMOBANK_SEED", "DEMOBANK_ANCHOR_DATE"):
        index = next(i for i, line in enumerate(lines) if line.startswith(f"{name}="))
        assert lines[index - 1].startswith("#"), name


# DEMOBANK_DATABASE_URL


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@db:5432/ledgerlens",
        "postgres://u:p@db:5432/ledgerlens",
        "postgresql+psycopg://u:p@db:5432/ledgerlens",
        "  postgresql://u:p@localhost/ledgerlens  ",
    ],
)
def test_database_url_accepts_the_postgres_schemes(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")
    monkeypatch.setenv("DEMOBANK_DATABASE_URL", url)

    assert get_settings().demobank_database_url.get_secret_value() == url


@pytest.mark.parametrize("blank", [None, "", "   "], ids=["unset", "empty", "spaces"])
def test_database_url_unset_or_blank(monkeypatch: pytest.MonkeyPatch, blank: str | None) -> None:
    monkeypatch.delenv("DEMOBANK_DATABASE_URL")
    variables = {"DEMOBANK_API_KEY": "test-api-key"}
    if blank is not None:
        variables["DEMOBANK_DATABASE_URL"] = blank

    assert error_lines(monkeypatch, **variables) == [MISSING_DATABASE_URL]


@pytest.mark.parametrize(
    "url",
    [
        f"mysql://u:{PASSWORD_MARKER}@db:3306/ledgerlens",
        f"postgresql+asyncpg://u:{PASSWORD_MARKER}@db/ledgerlens",
        f"sqlite:///{PASSWORD_MARKER}.db",
        f"u:{PASSWORD_MARKER}@db/ledgerlens",
    ],
)
def test_database_url_with_another_scheme(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    lines = error_lines(monkeypatch, DEMOBANK_API_KEY="test-api-key", DEMOBANK_DATABASE_URL=url)

    assert lines == [UNSUPPORTED_SCHEME]
    assert PASSWORD_MARKER not in "\n".join(lines)


def test_database_url_that_cannot_be_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"postgresql://u:{PASSWORD_MARKER}@db:notaport/ledgerlens"

    lines = error_lines(monkeypatch, DEMOBANK_API_KEY="test-api-key", DEMOBANK_DATABASE_URL=url)

    assert lines == ["DEMOBANK_DATABASE_URL has an invalid value"]


def test_database_url_is_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")
    monkeypatch.setenv("DEMOBANK_DATABASE_URL", f"postgresql://u:{PASSWORD_MARKER}@db/x")

    settings = get_settings()

    assert PASSWORD_MARKER not in repr(settings)
    assert PASSWORD_MARKER not in str(settings)
    assert PASSWORD_MARKER not in repr(settings.model_dump())


# DEMOBANK_SEED


@pytest.mark.parametrize(
    ("value", "expected"), [("0", 0), ("42", 42), (" 7 ", 7), ("10" * 20, int("10" * 20))]
)
def test_seed_accepts_a_non_negative_integer(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: int
) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")
    monkeypatch.setenv("DEMOBANK_SEED", value)

    assert get_settings().demobank_seed == expected


@pytest.mark.parametrize("blank", ["", "  "])
def test_blank_seed_gives_the_default(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")
    monkeypatch.setenv("DEMOBANK_SEED", blank)

    assert get_settings().demobank_seed == 42


@pytest.mark.parametrize("value", ["-1", "abc", "1.5", "+5", "1_000", "4 2", "\u0663", "1e3"])
def test_seed_that_is_not_a_non_negative_integer(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    lines = error_lines(monkeypatch, DEMOBANK_API_KEY="test-api-key", DEMOBANK_SEED=value)

    assert lines == [INVALID_SEED]


# DEMOBANK_ANCHOR_DATE


@pytest.mark.parametrize("blank", ["", "  "])
def test_blank_anchor_date_is_unset(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")
    monkeypatch.setenv("DEMOBANK_ANCHOR_DATE", blank)

    assert get_settings().demobank_anchor_date is None


@pytest.mark.parametrize(
    "value",
    [
        "2026-13-01",
        "yesterday",
        "2026-02-30",
        "2025-02-29",
        "20260630",
        "2026-6-30",
        "26-06-30",
        "2026-06-30T00:00",
    ],
)
def test_anchor_date_that_is_not_a_date(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    lines = error_lines(monkeypatch, DEMOBANK_API_KEY="test-api-key", DEMOBANK_ANCHOR_DATE=value)

    assert lines == [INVALID_ANCHOR_DATE]


def test_every_new_problem_is_reported_one_per_line(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = error_lines(
        monkeypatch,
        DEMOBANK_API_KEY="test-api-key",
        DEMOBANK_DATABASE_URL=f"mysql://u:{PASSWORD_MARKER}@db/x",
        DEMOBANK_SEED="-1",
        DEMOBANK_ANCHOR_DATE="yesterday",
    )

    assert lines == [UNSUPPORTED_SCHEME, INVALID_SEED, INVALID_ANCHOR_DATE]


@pytest.mark.parametrize(
    ("variables", "expected"),
    [
        ({"DEMOBANK_DATABASE_URL": ""}, MISSING_DATABASE_URL),
        ({"DEMOBANK_DATABASE_URL": "  "}, MISSING_DATABASE_URL),
        ({"DEMOBANK_DATABASE_URL": f"mysql://u:{PASSWORD_MARKER}@db/x"}, UNSUPPORTED_SCHEME),
        ({"DEMOBANK_SEED": "-1"}, INVALID_SEED),
        ({"DEMOBANK_SEED": "abc"}, INVALID_SEED),
        ({"DEMOBANK_ANCHOR_DATE": "2026-13-01"}, INVALID_ANCHOR_DATE),
        ({"DEMOBANK_ANCHOR_DATE": "yesterday"}, INVALID_ANCHOR_DATE),
    ],
    ids=[
        "url-empty",
        "url-blank",
        "url-mysql",
        "seed-negative",
        "seed-abc",
        "date-13",
        "date-word",
    ],
)
def test_module_reports_each_new_setting_without_its_value(
    variables: dict[str, str], expected: str
) -> None:
    # A marker password is in the URL of every case where the URL is valid too.
    environment = {
        "DEMOBANK_API_KEY": API_KEY_MARKER,
        "DEMOBANK_DATABASE_URL": f"postgresql://u:{PASSWORD_MARKER}@db/x",
        **variables,
    }

    result = run_module(environment)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"{expected}\n"
    assert "Traceback" not in result.stderr
    assert "MARKER" not in result.stdout + result.stderr


def test_module_does_not_connect_to_the_database() -> None:
    # Port 1 is closed: a connection attempt would fail. The check passes.
    environment = {
        "DEMOBANK_API_KEY": API_KEY_MARKER,
        "DEMOBANK_DATABASE_URL": f"postgresql://u:{PASSWORD_MARKER}@127.0.0.1:1/x",
        "DEMOBANK_SEED": "7",
        "DEMOBANK_ANCHOR_DATE": "2026-06-30",
    }

    result = run_module(environment)

    assert result.returncode == 0
    assert result.stdout == "Configuration OK\n"
    assert result.stderr == ""
