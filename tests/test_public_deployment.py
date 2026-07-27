from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from scripts.verify_public_deployment import (
    REQUIRED_ARTIFACTS,
    verify_public_deployment,
)


def _public_tree(tmp_path: Path) -> Path:
    public_root = tmp_path / "public"
    for index, relative_path in enumerate(REQUIRED_ARTIFACTS):
        destination = public_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(f"artifact-{index}".encode())
    return public_root


def test_public_deployment_gate_accepts_exact_evidence_and_assets(tmp_path: Path) -> None:
    public_root = _public_tree(tmp_path)
    responses = {
        "/": b'<title>SciGuard Autopilot</title><script src="/assets/judge.js"></script>',
        "/assets/judge.js": b"console.log('judge');",
        **{
            f"/{path}": (public_root / path).read_bytes()
            for path in REQUIRED_ARTIFACTS
        },
    }

    checks = verify_public_deployment(
        "https://judge.example/",
        public_root=public_root,
        fetch=lambda url: responses[urlparse(url).path],
    )

    assert checks
    assert {check.status for check in checks} == {"PASS"}


def test_public_deployment_gate_rejects_stale_or_fallback_html(tmp_path: Path) -> None:
    public_root = _public_tree(tmp_path)

    def stale_fetch(url: str) -> bytes:
        path = urlparse(url).path
        if path == "/":
            return b"<title>SciGuard Autopilot</title>"
        return b"<title>SciGuard Autopilot</title>"

    checks = verify_public_deployment(
        "https://judge.example/",
        public_root=public_root,
        fetch=stale_fetch,
    )

    artifact_checks = [check for check in checks if check.path in REQUIRED_ARTIFACTS]
    assert len(artifact_checks) == len(REQUIRED_ARTIFACTS)
    assert {check.status for check in artifact_checks} == {"FAIL"}
    assert all("stale" in check.detail for check in artifact_checks)
