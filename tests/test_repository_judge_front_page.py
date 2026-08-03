import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_readme_is_judge_first_and_evidence_linked() -> None:
    readme_path = ROOT / "README.md"
    readme = readme_path.read_text(encoding="utf-8")

    assert len(readme.splitlines()) <= 260
    required = (
        "Protect the scientific decision—not just the data pipeline.",
        "Judge it in 90 seconds",
        "https://sciguard-autopilot-demo.pages.dev/",
        "examples/outputs/datahub_live_receipt.json",
        "examples/outputs/evaluation_report.json",
        "examples/outputs/github_live_evidence.json",
        "https://github.com/songjie6816-code/sciguard-repair-sandbox/pull/2",
        "Live, recorded, and deliberately unclaimed",
        "make judge-check",
    )
    for marker in required:
        assert marker in readme

    lowered = readme.lower()
    assert "p0-judge-final-1280x720" not in lowered
    assert "live backend offline" not in lowered


def test_repository_workflows_are_parseable_and_named() -> None:
    workflow_dir = ROOT / ".github" / "workflows"
    workflows = {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in workflow_dir.glob("*.yml")
    }

    assert workflows["ci.yml"]["name"] == "CI"
    assert workflows["judge-health.yml"]["name"] == "Judge Health"
    assert "permissions" in workflows["ci.yml"]
    assert "permissions" in workflows["judge-health.yml"]


def test_readme_local_links_resolve() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"!?(?:\[[^]]*\])\(([^)]+)\)", readme)

    missing = []
    for raw_target in targets:
        target = raw_target.strip("<>").split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        if not (ROOT / target).exists():
            missing.append(target)

    assert missing == []


def test_judge_check_is_the_single_repository_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "judge-check: check" in makefile
    assert "evaluation.harness" in makefile
    assert "examples/outputs/evaluation_report.json" in makefile
    assert "$(PNPM) --dir web test" in makefile

    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "make check evidence-check" in ci
