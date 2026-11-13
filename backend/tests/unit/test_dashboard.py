"""The Grafana dashboard "LedgerLens sync" (#126), read from its provisioning files.

The live behaviour (home page, panels with data) is checked against the
Compose stack; these tests pin the dashboard's panels and queries, its
privacy (no query touches a field that could hold customer data), the
provider file and the otel-lgtm mounts and home page setting.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # PyYAML, from uvicorn[standard]; no stubs

ROOT = Path(__file__).resolve().parents[3]
DASHBOARD_FILE = ROOT / "observability/grafana/dashboards/ledgerlens-sync.json"
PROVIDER_FILE = ROOT / "observability/grafana/provisioning/dashboards/ledgerlens.yaml"
DASHBOARDS_MOUNT = "/otel-lgtm/ledgerlens-dashboards"
PROVIDER_MOUNT = "/otel-lgtm/grafana/conf/provisioning/dashboards/ledgerlens.yaml"
IMAGE = "grafana/otel-lgtm:0.37.0"

SYNC_TRACES = '{resource.service.name="ledgerlens-backend" && name="POST /api/sync"}'
SYNC_LOGS = '{service_name="ledgerlens-backend"} |~ "sync finished|sync failed|anomaly rule"'

# (title, type, data source uid, query, legend)
PANELS: list[tuple[str, str, str | None, str | None, str | None]] = [
    (
        "Sync runs by outcome (since backend start)",
        "stat",
        "prometheus",
        "sum by (outcome) (ledgerlens_sync_runs_total)",
        "{{outcome}}",
    ),
    (
        "Sync duration p95 (since backend start)",
        "stat",
        "prometheus",
        "histogram_quantile(0.95, sum by (le) (ledgerlens_sync_duration_seconds_bucket))",
        None,
    ),
    (
        "Transactions created, skipped, rejected (since backend start)",
        "stat",
        "prometheus",
        "sum by (result) (ledgerlens_sync_transactions_total)",
        "{{result}}",
    ),
    (
        "Anomaly flags by rule (since backend start)",
        "stat",
        "prometheus",
        "sum by (rule) (ledgerlens_anomaly_flags_total)",
        "{{rule}}",
    ),
    (
        "HTTP request rate by route",
        "timeseries",
        "prometheus",
        "sum by (service_name, http_route) "
        "(rate(http_server_request_duration_seconds_count[$__rate_interval]))",
        "{{service_name}} {{http_route}}",
    ),
    (
        "HTTP latency p95 by route",
        "timeseries",
        "prometheus",
        "histogram_quantile(0.95, sum by (service_name, http_route, le) "
        "(rate(http_server_request_duration_seconds_bucket[$__rate_interval])))",
        "{{service_name}} {{http_route}}",
    ),
    ("Recent sync traces", "table", "tempo", SYNC_TRACES, None),
    ("Recent sync log lines", "logs", "loki", SYNC_LOGS, None),
    ("Alert: LedgerLens sync failing", "alertlist", None, None, None),
]

PRIVATE_WORDS = (
    "amount",
    "description",
    "counterparty",
    "reference",
    "balance",
    "iban",
    "account_number",
)
ALLOWED_LABELS = {"outcome", "result", "rule", "le", "service_name", "http_route"}


@pytest.fixture(scope="module")
def dashboard() -> dict[str, Any]:
    found = json.loads(DASHBOARD_FILE.read_text())
    assert isinstance(found, dict)
    return found


@pytest.fixture(scope="module")
def otel_lgtm() -> dict[str, Any]:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    service = compose["services"]["otel-lgtm"]
    assert isinstance(service, dict)
    return service


def query_of(panel: dict[str, Any]) -> str | None:
    targets = panel.get("targets", [])
    if not targets:
        return None
    [target] = targets
    value = target.get("expr", target.get("query"))
    assert isinstance(value, str)
    return value


def test_the_dashboard_has_its_uid_title_time_range_and_refresh(dashboard: dict[str, Any]) -> None:
    assert dashboard["uid"] == "ledgerlens-sync"
    assert dashboard["title"] == "LedgerLens sync"
    assert dashboard["time"] == {"from": "now-1h", "to": "now"}
    assert dashboard["refresh"] == "30s"
    assert dashboard.get("templating", {}).get("list", []) == []


def test_it_holds_the_nine_panels_in_order(dashboard: dict[str, Any]) -> None:
    panels = dashboard["panels"]
    assert [panel["title"] for panel in panels] == [title for title, *_ in PANELS]
    for panel, (_, kind, uid, query, legend) in zip(panels, PANELS, strict=True):
        assert panel["type"] == kind, panel["title"]
        assert query_of(panel) == query, panel["title"]
        if uid is None:
            assert "datasource" not in panel
            assert "targets" not in panel
            continue
        assert panel["datasource"]["uid"] == uid
        [target] = panel["targets"]
        assert target["datasource"]["uid"] == uid
        assert target.get("legendFormat") == legend, panel["title"]


def test_data_sources_are_given_by_uid_never_by_name(dashboard: dict[str, Any]) -> None:
    text = DASHBOARD_FILE.read_text()
    assert "${DS_" not in text
    for panel in dashboard["panels"]:
        for holder in [panel, *panel.get("targets", [])]:
            if "datasource" in holder:
                assert isinstance(holder["datasource"], dict)
                assert set(holder["datasource"]) == {"type", "uid"}


def test_units_and_the_no_sync_yet_value(dashboard: dict[str, Any]) -> None:
    panels = dashboard["panels"]
    units = [panel["fieldConfig"]["defaults"].get("unit") for panel in panels[:6]]
    assert units == [None, "s", None, None, "reqps", "s"]
    no_values = [panel["fieldConfig"]["defaults"].get("noValue") for panel in panels[:4]]
    assert no_values == [None, "No sync yet", "No sync yet", "No sync yet"]


def test_the_traces_panel_uses_traceql_with_a_limit_of_20(dashboard: dict[str, Any]) -> None:
    [target] = dashboard["panels"][6]["targets"]
    assert target["queryType"] == "traceql"
    assert target["limit"] == 20
    # The trace list columns only: no added attribute column or transformation.
    assert dashboard["panels"][6]["fieldConfig"]["overrides"] == []
    assert dashboard["panels"][6].get("transformations", []) == []


def test_the_alert_list_shows_the_sync_rule_in_every_state(dashboard: dict[str, Any]) -> None:
    options = dashboard["panels"][8]["options"]
    assert options["alertName"] == "LedgerLens sync failing"
    states = options["stateFilter"]
    assert all(states[state] for state in ("normal", "pending", "firing", "noData", "error"))
    assert options["showInactiveAlerts"] is True


def test_no_query_touches_customer_data(dashboard: dict[str, Any]) -> None:
    for panel in dashboard["panels"]:
        query = query_of(panel)
        if query is None:
            continue
        lowered = query.lower()
        for word in PRIVATE_WORDS:
            assert word not in lowered, (panel["title"], word)
        for grouping in re.findall(r"by \(([^)]*)\)", query):
            labels = {label.strip() for label in grouping.split(",")}
            assert labels <= ALLOWED_LABELS, panel["title"]


def test_the_log_panel_adds_no_parsed_fields(dashboard: dict[str, Any]) -> None:
    query = query_of(dashboard["panels"][7])
    assert query is not None
    for stage in ("| json", "| logfmt", "| line_format", "| label_format", "| regexp", "| pattern"):
        assert stage not in query


def test_the_provider_adds_a_read_only_ledgerlens_folder() -> None:
    assert PROVIDER_FILE.name not in {"grafana-dashboards.yaml", "sample.yaml"}
    config = yaml.safe_load(PROVIDER_FILE.read_text())
    [provider] = config["providers"]
    assert provider["name"] == "LedgerLens"
    assert provider["type"] == "file"
    assert provider["folder"] == "LedgerLens"
    assert provider["allowUiUpdates"] is False
    assert provider["options"]["path"] == DASHBOARDS_MOUNT


def test_compose_mounts_both_read_only_and_sets_the_home_dashboard(
    otel_lgtm: dict[str, Any],
) -> None:
    assert otel_lgtm["image"] == IMAGE
    volumes = otel_lgtm["volumes"]
    assert f"./{PROVIDER_FILE.relative_to(ROOT)}:{PROVIDER_MOUNT}:ro" in volumes
    assert f"./{DASHBOARD_FILE.parent.relative_to(ROOT)}:{DASHBOARDS_MOUNT}:ro" in volumes
    environment = otel_lgtm["environment"]
    assert environment == {
        "GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH": f"{DASHBOARDS_MOUNT}/{DASHBOARD_FILE.name}"
    }
