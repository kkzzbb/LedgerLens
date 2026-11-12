import subprocess
import sys
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from ledgerlens.config import (
    ConfigError,
    Settings,
    env_name,
    get_settings,
    load_settings_or_exit,
)

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"
BACKEND_DIR = Path(__file__).resolve().parents[2]

ALL_VARIABLES = [env_name(field) for field in Settings.model_fields]
SECRET_MARKERS = {
    "DATABASE_URL": "MARKER-database-url",
    "DEMOBANK_API_KEY": "MARKER-demobank-api-key",
    "ANTHROPIC_API_KEY": "MARKER-anthropic-api-key",
}
INTEGER_VARIABLES = [
    "SYNC_INTERVAL_SECONDS",
    "SYNC_PAGE_SIZE",
    "STALE_THRESHOLD_MINUTES",
    "FAILURE_STREAK_THRESHOLD",
    "ANOMALY_EVALUATION_WINDOW_DAYS",
    "ANOMALY_DUPLICATE_WINDOW_DAYS",
    "ANOMALY_MIN_HISTORY_COUNT",
    "ANOMALY_BASELINE_DAYS",
]
AT_LEAST_ONE_VARIABLES = [
    name
    for name in INTEGER_VARIABLES
    if name not in {"SYNC_PAGE_SIZE", "ANOMALY_DUPLICATE_WINDOW_DAYS"}
]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No settings variable is set and nothing is cached, before and after."""
    for name in ALL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sets the two required variables."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@localhost:5432/test")
    monkeypatch.setenv("DEMOBANK_API_KEY", "test-api-key")


def error_lines(monkeypatch: pytest.MonkeyPatch, **variables: str) -> list[str]:
    """Sets the variables and returns the lines of the resulting ConfigError."""
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError) as caught:
        get_settings()
    return str(caught.value).splitlines()


def assert_only_problem(lines: list[str], name: str) -> None:
    assert len(lines) == 1
    assert lines[0].startswith(f"{name} ")


# Defaults and overrides


def test_field_names_cover_the_documented_variables() -> None:
    assert set(ALL_VARIABLES) == {
        "DATABASE_URL",
        "DEMOBANK_API_KEY",
        "DEMOBANK_BASE_URL",
        "DEMO_MODE",
        "SYNC_INTERVAL_SECONDS",
        "SYNC_PAGE_SIZE",
        "STALE_THRESHOLD_MINUTES",
        "FAILURE_STREAK_THRESHOLD",
        "ANTHROPIC_API_KEY",
        "AGENT_MODEL",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "ANOMALY_EVALUATION_WINDOW_DAYS",
        "ANOMALY_DUPLICATE_WINDOW_DAYS",
        "ANOMALY_DUPLICATE_AMOUNT_TOLERANCE_PERCENT",
        "ANOMALY_LARGE_EXPENSE_ABSOLUTE",
        "ANOMALY_LARGE_EXPENSE_MULTIPLIER",
        "ANOMALY_MIN_HISTORY_COUNT",
        "ANOMALY_BASELINE_DAYS",
    }


@pytest.mark.usefixtures("required")
def test_defaults() -> None:
    settings = get_settings()

    assert settings.database_url.get_secret_value() == "postgresql://user:pw@localhost:5432/test"
    assert settings.demobank_api_key.get_secret_value() == "test-api-key"
    assert settings.demobank_base_url == "http://demobank:8100"
    assert settings.demo_mode is True
    assert settings.sync_interval_seconds == 120
    assert settings.sync_page_size == 100
    assert settings.stale_threshold_minutes == 30
    assert settings.failure_streak_threshold == 3
    assert settings.anthropic_api_key.get_secret_value() == ""
    assert settings.agent_model == "claude-opus-5-5"
    assert settings.otel_exporter_otlp_endpoint == ""
    assert settings.anomaly_evaluation_window_days == 7
    assert settings.anomaly_duplicate_window_days == 3
    assert settings.anomaly_duplicate_amount_tolerance_percent == Decimal("1")
    assert settings.anomaly_large_expense_absolute == Decimal("5000.00")
    assert settings.anomaly_large_expense_multiplier == Decimal("3")
    assert settings.anomaly_min_history_count == 3
    assert settings.anomaly_baseline_days == 90


def test_overrides_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    overrides = {
        "DATABASE_URL": "postgresql://other:pw@dbhost:5432/other",
        "DEMOBANK_API_KEY": "other-api-key",
        "DEMOBANK_BASE_URL": "http://localhost:9999",
        "DEMO_MODE": "false",
        "SYNC_INTERVAL_SECONDS": "60",
        "SYNC_PAGE_SIZE": "250",
        "STALE_THRESHOLD_MINUTES": "15",
        "FAILURE_STREAK_THRESHOLD": "9",
        "ANTHROPIC_API_KEY": "other-anthropic-key",
        "AGENT_MODEL": "some-other-model",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector:4318",
        "ANOMALY_EVALUATION_WINDOW_DAYS": "14",
        "ANOMALY_DUPLICATE_WINDOW_DAYS": "0",
        "ANOMALY_DUPLICATE_AMOUNT_TOLERANCE_PERCENT": "2.5",
        "ANOMALY_LARGE_EXPENSE_ABSOLUTE": "0",
        "ANOMALY_LARGE_EXPENSE_MULTIPLIER": "2.5",
        "ANOMALY_MIN_HISTORY_COUNT": "1",
        "ANOMALY_BASELINE_DAYS": "30",
    }
    assert set(overrides) == set(ALL_VARIABLES)
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)

    settings = get_settings()

    assert settings.database_url.get_secret_value() == "postgresql://other:pw@dbhost:5432/other"
    assert settings.demobank_api_key.get_secret_value() == "other-api-key"
    assert settings.demobank_base_url == "http://localhost:9999"
    assert settings.demo_mode is False
    assert settings.sync_interval_seconds == 60
    assert settings.sync_page_size == 250
    assert settings.stale_threshold_minutes == 15
    assert settings.failure_streak_threshold == 9
    assert settings.anthropic_api_key.get_secret_value() == "other-anthropic-key"
    assert settings.agent_model == "some-other-model"
    assert settings.otel_exporter_otlp_endpoint == "http://otel-collector:4318"
    assert settings.anomaly_evaluation_window_days == 14
    assert settings.anomaly_duplicate_window_days == 0
    assert settings.anomaly_duplicate_amount_tolerance_percent == Decimal("2.5")
    assert settings.anomaly_large_expense_absolute == Decimal("0")
    assert settings.anomaly_large_expense_multiplier == Decimal("2.5")
    assert settings.anomaly_min_history_count == 1
    assert settings.anomaly_baseline_days == 30


# Caching


@pytest.mark.usefixtures("required")
def test_get_settings_returns_the_same_cached_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    first = get_settings()
    monkeypatch.setenv("SYNC_INTERVAL_SECONDS", "60")

    assert get_settings() is first
    assert get_settings().sync_interval_seconds == 120


@pytest.mark.usefixtures("required")
def test_cache_clear_makes_get_settings_read_the_environment_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = get_settings()
    monkeypatch.setenv("SYNC_INTERVAL_SECONDS", "60")
    get_settings.cache_clear()

    second = get_settings()

    assert second is not first
    assert second.sync_interval_seconds == 60


# Environment only


def test_env_file_in_the_working_directory_is_not_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql://from:dotenv@db:5432/dotenv\nDEMOBANK_API_KEY=from-dotenv\n"
    )
    monkeypatch.chdir(tmp_path)

    lines = error_lines(monkeypatch)

    assert any(line.startswith("DATABASE_URL ") for line in lines)


@pytest.mark.usefixtures("required")
def test_constructor_arguments_are_not_a_source() -> None:
    settings = Settings(sync_interval_seconds=7)

    assert settings.sync_interval_seconds == 120


# Missing and blank values


def test_both_required_variables_missing_are_reported_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = error_lines(monkeypatch)

    assert len(lines) == 2
    assert lines[0].startswith("DATABASE_URL ")
    assert lines[1].startswith("DEMOBANK_API_KEY ")


@pytest.mark.parametrize("name", ["DATABASE_URL", "DEMOBANK_API_KEY"])
def test_one_required_variable_missing(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    other = "DEMOBANK_API_KEY" if name == "DATABASE_URL" else "DATABASE_URL"

    assert_only_problem(error_lines(monkeypatch, **{other: "set"}), name)


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
@pytest.mark.parametrize("name", ["DATABASE_URL", "DEMOBANK_API_KEY"])
def test_blank_required_variable_fails_as_missing(
    monkeypatch: pytest.MonkeyPatch, name: str, blank: str
) -> None:
    other = "DEMOBANK_API_KEY" if name == "DATABASE_URL" else "DATABASE_URL"

    lines = error_lines(monkeypatch, **{other: "set", name: blank})

    assert_only_problem(lines, name)
    assert "not set" in lines[0]


@pytest.mark.usefixtures("required")
@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_optional_variables_give_the_defaults(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    optional = [n for n in ALL_VARIABLES if n not in ("DATABASE_URL", "DEMOBANK_API_KEY")]
    for name in optional:
        monkeypatch.setenv(name, blank)

    settings = get_settings()

    assert settings.sync_interval_seconds == 120
    assert settings.model_dump(exclude={"database_url", "demobank_api_key"}) == {
        field: info.default
        for field, info in Settings.model_fields.items()
        if field not in ("database_url", "demobank_api_key")
    }


# Invalid values


@pytest.mark.usefixtures("required")
@pytest.mark.parametrize("value", ["abc", "1.5", "1.0", "1e3", "0x10", "1_000"])
@pytest.mark.parametrize("name", INTEGER_VARIABLES)
def test_non_integer_value_is_invalid(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    assert_only_problem(error_lines(monkeypatch, **{name: value}), name)


@pytest.mark.usefixtures("required")
@pytest.mark.parametrize("value", ["0", "-1"])
@pytest.mark.parametrize("name", AT_LEAST_ONE_VARIABLES)
def test_value_below_one_is_invalid(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    assert_only_problem(error_lines(monkeypatch, **{name: value}), name)


@pytest.mark.usefixtures("required")
@pytest.mark.parametrize("name", AT_LEAST_ONE_VARIABLES)
def test_value_of_one_is_accepted(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "1")

    assert getattr(get_settings(), name.lower()) == 1


@pytest.mark.usefixtures("required")
@pytest.mark.parametrize("value", ["0", "501", "-5"])
def test_page_size_outside_1_to_500_is_invalid(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    assert_only_problem(error_lines(monkeypatch, SYNC_PAGE_SIZE=value), "SYNC_PAGE_SIZE")


@pytest.mark.usefixtures("required")
@pytest.mark.parametrize("value", [1, 500])
def test_page_size_bounds_are_accepted(monkeypatch: pytest.MonkeyPatch, value: int) -> None:
    monkeypatch.setenv("SYNC_PAGE_SIZE", str(value))

    assert get_settings().sync_page_size == value


@pytest.mark.usefixtures("required")
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
def test_demo_mode_accepts_booleans_in_any_case(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv("DEMO_MODE", value)

    assert get_settings().demo_mode is expected


@pytest.mark.usefixtures("required")
@pytest.mark.parametrize("value", ["maybe", "2", "yes", "truee"])
def test_demo_mode_that_is_not_a_boolean_is_invalid(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    assert_only_problem(error_lines(monkeypatch, DEMO_MODE=value), "DEMO_MODE")


def test_all_problems_are_reported_one_per_line(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = error_lines(
        monkeypatch,
        DEMO_MODE="maybe",
        SYNC_INTERVAL_SECONDS="abc",
        SYNC_PAGE_SIZE="501",
    )

    assert [line.split(" ")[0] for line in lines] == [
        "DATABASE_URL",
        "DEMOBANK_API_KEY",
        "DEMO_MODE",
        "SYNC_INTERVAL_SECONDS",
        "SYNC_PAGE_SIZE",
    ]


# Secrets


def test_repr_and_str_do_not_contain_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, marker in SECRET_MARKERS.items():
        monkeypatch.setenv(name, marker)

    settings = get_settings()

    for name, marker in SECRET_MARKERS.items():
        assert getattr(settings, name.lower()).get_secret_value() == marker
        assert marker not in repr(settings)
        assert marker not in str(settings)
    assert "MARKER" not in repr(settings)
    assert "MARKER" not in str(settings)


@pytest.mark.parametrize(
    "invalid",
    [
        {"SYNC_INTERVAL_SECONDS": "MARKER-not-an-integer"},
        {"SYNC_PAGE_SIZE": "98765"},
        {"STALE_THRESHOLD_MINUTES": "-98765"},
        {"DEMO_MODE": "MARKER-not-a-boolean"},
    ],
    ids=["non-integer", "page-size", "below-one", "demo-mode"],
)
def test_config_error_never_contains_a_value(
    monkeypatch: pytest.MonkeyPatch, invalid: dict[str, str]
) -> None:
    for name, marker in SECRET_MARKERS.items():
        monkeypatch.setenv(name, marker)
    for name, value in invalid.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ConfigError) as caught:
        get_settings()

    shown = f"{caught.value}\n{caught.value!r}\n{caught.value.args!r}"
    for value in [*SECRET_MARKERS.values(), *invalid.values()]:
        assert value not in shown
    assert "MARKER" not in shown
    # Nothing that holds the input values is chained to the error.
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


# agents_enabled


@pytest.mark.usefixtures("required")
@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, False), ("", False), ("   ", False), ("fake-anthropic-key", True)],
)
def test_agents_enabled_only_with_a_non_blank_key(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: bool
) -> None:
    if value is not None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", value)

    assert get_settings().agents_enabled is expected


# load_settings_or_exit and `python -m ledgerlens.config`


@pytest.mark.usefixtures("required")
def test_load_settings_or_exit_returns_valid_settings() -> None:
    assert load_settings_or_exit() is get_settings()


def test_load_settings_or_exit_prints_the_problems_and_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        load_settings_or_exit()

    captured = capsys.readouterr()
    assert caught.value.code == 1
    assert captured.out == ""
    assert captured.err.splitlines()[0].startswith("DATABASE_URL ")
    assert "DEMOBANK_API_KEY" in captured.err
    assert "Traceback" not in captured.err


def run_module(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Runs `python -m ledgerlens.config` with exactly the given environment."""
    return subprocess.run(
        [sys.executable, "-m", "ledgerlens.config"],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_module_prints_configuration_ok_and_no_values() -> None:
    result = run_module(SECRET_MARKERS)

    assert result.returncode == 0
    assert result.stdout == "Configuration OK\n"
    assert result.stderr == ""


def test_module_names_the_missing_variable_without_a_traceback() -> None:
    result = run_module(
        {
            "DEMOBANK_API_KEY": SECRET_MARKERS["DEMOBANK_API_KEY"],
            "SYNC_PAGE_SIZE": "MARKER-page-size",
        }
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "DATABASE_URL" in output
    assert "SYNC_PAGE_SIZE" in output
    assert "Traceback" not in output
    assert "MARKER" not in output
    assert result.stdout == ""


# .env.example


def test_env_example_has_a_line_for_every_settings_variable() -> None:
    lines = ENV_EXAMPLE.read_text().splitlines()

    missing = [
        name for name in ALL_VARIABLES if not any(line.startswith(f"{name}=") for line in lines)
    ]

    assert missing == []


def test_env_example_carries_the_defaults_of_the_optional_variables() -> None:
    values = dict(
        line.split("=", 1)
        for line in ENV_EXAMPLE.read_text().splitlines()
        if line and not line.startswith("#")
    )

    for field, info in Settings.model_fields.items():
        if info.is_required():
            continue
        default = info.default
        if hasattr(default, "get_secret_value"):
            default = default.get_secret_value()
        expected = str(default).lower() if isinstance(default, bool) else str(default)
        assert values[env_name(field)] == expected


# Anomaly settings


@pytest.mark.usefixtures("required")
def test_duplicate_window_of_zero_is_accepted_and_below_zero_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANOMALY_DUPLICATE_WINDOW_DAYS", "0")
    assert get_settings().anomaly_duplicate_window_days == 0
    get_settings.cache_clear()

    assert_only_problem(
        error_lines(monkeypatch, ANOMALY_DUPLICATE_WINDOW_DAYS="-1"),
        "ANOMALY_DUPLICATE_WINDOW_DAYS",
    )


@pytest.mark.usefixtures("required")
@pytest.mark.parametrize("value", ["0", "100", "0.5"])
def test_tolerance_from_0_to_100_is_accepted(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("ANOMALY_DUPLICATE_AMOUNT_TOLERANCE_PERCENT", value)

    assert get_settings().anomaly_duplicate_amount_tolerance_percent == Decimal(value)


@pytest.mark.usefixtures("required")
@pytest.mark.parametrize("value", ["-0.01", "100.01", "MARKER-abc", "NaN"])
def test_invalid_tolerance_fails_without_the_value(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    lines = error_lines(monkeypatch, ANOMALY_DUPLICATE_AMOUNT_TOLERANCE_PERCENT=value)

    assert_only_problem(lines, "ANOMALY_DUPLICATE_AMOUNT_TOLERANCE_PERCENT")
    assert value not in lines[0]


@pytest.mark.usefixtures("required")
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ANOMALY_LARGE_EXPENSE_ABSOLUTE", "-0.01"),
        ("ANOMALY_LARGE_EXPENSE_ABSOLUTE", "NaN"),
        ("ANOMALY_LARGE_EXPENSE_MULTIPLIER", "-1.5"),
        ("ANOMALY_LARGE_EXPENSE_MULTIPLIER", "MARKER-abc"),
    ],
)
def test_invalid_large_expense_amount_fails_without_the_value(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    lines = error_lines(monkeypatch, **{name: value})

    assert_only_problem(lines, name)
    assert value not in lines[0]
