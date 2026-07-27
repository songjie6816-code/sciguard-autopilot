import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_curated_machine_evaluation_is_gated_and_matches_public_artifact() -> None:
    golden = ROOT / "examples" / "outputs" / "evaluation_report.json"
    public = ROOT / "web" / "public" / "evidence" / "evaluation_report.json"
    report = json.loads(golden.read_text(encoding="utf-8"))

    assert public.read_bytes() == golden.read_bytes()
    assert report["capture_type"] == "CONTROLLED_DATAHUB_ABLATION"
    assert report["gate"] == {"failures": [], "status": "PASS"}
    assert report["benchmark"]["scenario_count"] == 13
    assert len(report["benchmark"]["scenario_spec_sha256"]) == 64
    assert [
        {
            "id": arm["id"],
            "precision": arm["precision"],
            "recall": arm["recall"],
            "f1": arm["f1"],
            "exact": f"{arm['exact_cones']}/{arm['total_cones']}",
        }
        for arm in report["impact_arms"]
    ] == [
        {
            "id": "full-lineage",
            "precision": 1.0,
            "recall": 1.0,
            "f1": 1.0,
            "exact": "3/3",
        },
        {
            "id": "search-only",
            "precision": 0.6,
            "recall": 1.0,
            "f1": 0.75,
            "exact": "0/3",
        },
        {
            "id": "no-datahub",
            "precision": None,
            "recall": 0.0,
            "f1": 0.0,
            "exact": "0/3",
        },
    ]
    assert hashlib.sha256(public.read_bytes()).hexdigest()
