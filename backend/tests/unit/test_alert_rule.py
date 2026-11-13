"""The Grafana alert rule "LedgerLens sync failing" (#123), read from its provisioning file.

The live behaviour (Pending, Firing, Normal) is checked against the Compose
stack; these tests pin the rule's settings and its privacy: the labels and
annotations hold the rule name, `service_name` and `outcome` only.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # PyYAML, from uvicorn[standard]; no stubs

ROOT = Path(__file__).resolve().parents[3]
RULE_FILE = ROOT / "observability/grafana/provisioning/alerting/ledgerlens-sync.yaml"
MOUNT = "/otel-lgtm/grafana/conf/provisioning/alerting/ledgerlens-sync.yaml"
EXPR = 'sum(increase(ledgerlens_sync_runs_total{outcome="failed"}[10m]))'


@pytest.fixture(scope="module")
def group() -> dict[str, Any]:
    config = yaml.safe_load(RULE_FILE.read_text())
    [found] = config["groups"]
    assert isinstance(found, dict)
    return found


@pytest.fixture(scope="module")
def rule(group: dict[str, Any]) -> dict[str, Any]:
    [found] = group["rules"]
    assert isinstance(found, dict)
    return found


def test_the_rule_is_evaluated_every_minute_and_pends_one_minute(
    group: dict[str, Any], rule: dict[str, Any]
) -> None:
    assert rule["title"] == "LedgerLens sync failing"
    assert group["interval"] == "1m"
    assert rule["for"] == "1m"


def test_it_fires_when_failed_runs_increased_in_ten_minutes(rule: dict[str, Any]) -> None:
    queries = {query["refId"]: query for query in rule["data"]}
    assert queries["A"]["datasourceUid"] == "prometheus"
    assert queries["A"]["model"]["expr"] == EXPR
    condition = queries[rule["condition"]]["model"]
    assert condition["expression"] == "A"
    assert condition["conditions"][0]["evaluator"] == {"type": "gt", "params": [0]}


def test_no_data_is_normal(rule: dict[str, Any]) -> None:
    assert rule["noDataState"] == "OK"


def test_labels_and_annotations_hold_no_customer_data(rule: dict[str, Any]) -> None:
    assert rule["labels"] == {"service_name": "ledgerlens-backend", "outcome": "failed"}
    assert set(rule["annotations"]) == {"summary", "description"}
    text = " ".join(rule["annotations"].values())
    assert "{{" not in text  # no templated label or value


def test_compose_mounts_the_file_read_only_into_otel_lgtm() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    volumes = compose["services"]["otel-lgtm"]["volumes"]
    assert f"./{RULE_FILE.relative_to(ROOT)}:{MOUNT}:ro" in volumes
