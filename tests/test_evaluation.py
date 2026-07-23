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
            {
                "id": "positive",
                "is_positive": True,
                "detect_ok": True,
                "severity_ok": True,
                "actionable": True,
                "owner": PRF(tp=1, fp=0, fn=0),
                "control_ok": True,
                "latency_ms": 1.0,
            },
            {
                "id": "negative",
                "is_positive": False,
                "detect_ok": True,
                "severity_ok": True,
                "actionable": False,
                "owner": PRF(tp=0, fp=0, fn=0),
                "control_ok": True,
                "latency_ms": 1.0,
            },
        ],
        "impact": [
            {"dataset": "d", "expected": {"a", "b"}, "lineage": PRF(tp=2, fp=0, fn=0),
             "lineage_exact": True, "search": PRF(tp=2, fp=3, fn=0),
             "search_exact": False, "search_false_positives": ["x", "y", "z"]},
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


def test_gate_fails_on_missed_owners() -> None:
    r = _perfect_result()
    r["rows"][0]["owner"] = PRF(tp=0, fp=0, fn=3)  # notified nobody
    assert any("owner" in f for f in harness.gate(r))


def test_gate_fails_on_owner_spam() -> None:
    r = _perfect_result()
    r["rows"][0]["owner"] = PRF(tp=3, fp=50, fn=0)  # notified everyone
    assert any("owner" in f for f in harness.gate(r))


def test_gate_fails_on_control_target_regression() -> None:
    r = _perfect_result()
    r["rows"][0]["control_ok"] = False  # controlled nothing / wrong target
    assert any("control" in f for f in harness.gate(r))


def test_gate_fails_on_empty_evaluation() -> None:
    # Nothing evaluated must never read as a pass.
    assert harness.gate({"rows": [], "impact": []}) != []


def test_deterministic_summary_excludes_latency() -> None:
    report = harness.summarize(_perfect_result())
    assert "Latency" not in report
    assert "mean per-scenario" not in report


def test_performance_summary_is_explicitly_non_deterministic() -> None:
    report = harness.summarize_performance(_perfect_result())
    assert "NON-DETERMINISTIC" in report
    assert "mean per-scenario" in report


def test_default_main_does_not_update_golden(tmp_path, monkeypatch) -> None:
    golden = tmp_path / "golden.md"
    golden.write_text("curated\n", encoding="utf-8")
    output = tmp_path / "runtime" / "evaluation.md"
    performance = tmp_path / "runtime" / "performance.md"
    monkeypatch.setattr(harness, "GOLDEN_REPORT", golden)
    monkeypatch.setattr(harness, "DEFAULT_REPORT", output)
    monkeypatch.setattr(harness, "DEFAULT_PERFORMANCE_REPORT", performance)
    monkeypatch.setattr(harness, "run", _perfect_result)

    harness.main([])

    assert golden.read_text(encoding="utf-8") == "curated\n"
    assert output.read_text(encoding="utf-8") == harness.summarize(_perfect_result())
    assert "NON-DETERMINISTIC" in performance.read_text(encoding="utf-8")


def test_update_golden_requires_explicit_flag(tmp_path, monkeypatch) -> None:
    golden = tmp_path / "golden.md"
    output = tmp_path / "runtime" / "evaluation.md"
    performance = tmp_path / "runtime" / "performance.md"
    monkeypatch.setattr(harness, "GOLDEN_REPORT", golden)
    monkeypatch.setattr(harness, "DEFAULT_REPORT", output)
    monkeypatch.setattr(harness, "DEFAULT_PERFORMANCE_REPORT", performance)
    monkeypatch.setattr(harness, "run", _perfect_result)

    harness.main(["--update-golden"])

    assert golden.read_text(encoding="utf-8") == harness.summarize(_perfect_result())


def test_golden_output_path_is_rejected_without_update_flag(
    tmp_path,
    monkeypatch,
) -> None:
    golden = tmp_path / "golden.md"
    performance = tmp_path / "performance.md"
    monkeypatch.setattr(harness, "GOLDEN_REPORT", golden)
    monkeypatch.setattr(harness, "DEFAULT_PERFORMANCE_REPORT", performance)
    monkeypatch.setattr(harness, "run", _perfect_result)

    with pytest.raises(SystemExit, match="--update-golden"):
        harness.main(["--output", str(golden)])

    assert not golden.exists()


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
