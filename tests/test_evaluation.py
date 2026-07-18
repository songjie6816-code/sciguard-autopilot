"""Tests for the evaluation gate.

The gate-logic tests need no DataHub and prove the evaluation is NOT vacuous:
a broken system (over-broad impact, missed detection, false alarm) fails. The
live test runs the whole harness against DataHub and is skipped when it is down.
"""

import pytest

from evaluation import harness
from evaluation.metrics import PRF, aggregate


def _perfect_result() -> dict:
    return {
        "rows": [
            {"is_positive": True, "detect_ok": True, "severity_ok": True,
             "actionable": True, "owner_recall": PRF(tp=1, fp=0, fn=0),
             "tag_ok": True, "latency_ms": 1.0},
            {"is_positive": False, "detect_ok": True, "severity_ok": True,
             "actionable": False, "owner_recall": PRF(tp=0, fp=0, fn=0),
             "tag_ok": True, "latency_ms": 1.0},
        ],
        "impact": [
            {"dataset": "d", "expected": {"a", "b"}, "lineage": PRF(tp=2, fp=0, fn=0),
             "lineage_exact": True, "search": PRF(tp=2, fp=3, fn=0),
             "search_false_positives": ["x", "y", "z"]},
        ],
    }


def test_gate_passes_on_perfect_result() -> None:
    assert harness.gate(_perfect_result()) == []


def test_gate_fails_on_over_broad_lineage() -> None:
    r = _perfect_result()
    r["impact"][0]["lineage"] = PRF(tp=2, fp=4, fn=0)  # over-prediction
    r["impact"][0]["lineage_exact"] = False
    failures = harness.gate(r)
    assert any("exact" in f or "precision" in f for f in failures)


def test_gate_fails_on_missed_detection() -> None:
    r = _perfect_result()
    r["rows"][0]["detect_ok"] = False
    assert any("detection" in f for f in harness.gate(r))


def test_gate_fails_on_false_alarm() -> None:
    r = _perfect_result()
    r["rows"][1]["actionable"] = True  # negative control fired
    assert any("false alarm" in f for f in harness.gate(r))


def _graph_or_skip() -> None:
    try:
        from datahub_client.metadata_reader import connect

        connect()
    except Exception as exc:  # noqa: BLE001 - any connection issue skips the live test
        pytest.skip(f"DataHub not reachable: {exc}")


def test_live_evaluation_gate_passes() -> None:
    _graph_or_skip()
    assert harness.gate(harness.run()) == []


def test_live_search_baseline_is_less_precise_than_lineage() -> None:
    _graph_or_skip()
    result = harness.run()
    lineage = aggregate([i["lineage"] for i in result["impact"]])
    search = aggregate([i["search"] for i in result["impact"]])
    assert lineage.precision == 1.0
    assert search.precision < lineage.precision  # the point of the ablation
