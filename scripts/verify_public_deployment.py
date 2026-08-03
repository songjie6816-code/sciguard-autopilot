"""Fail closed unless the anonymous Judge deployment matches local public evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import certifi

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = ROOT / "web" / "public"
REQUIRED_ARTIFACTS = (
    "replays/inc-sciguard-b042-unit-contract/manifest.json",
    "replays/inc-sciguard-b042-unit-contract/events.jsonl",
    "replays/inc-sciguard-b042-unit-contract/repair-manifest.json",
    "replays/inc-sciguard-b042-unit-contract/repair-bundle.json",
    "evidence/datahub_live_receipt.json",
    "evidence/evaluation_report.json",
    "evidence/github_live_evidence.json",
)
ASSET_PATTERN = re.compile(rb"""(?:src|href)=["']([^"'?#]+\.(?:js|css))["']""")


@dataclass(frozen=True)
class DeploymentCheck:
    path: str
    status: str
    expected_sha256: str | None
    observed_sha256: str | None
    detail: str


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _download(url: str) -> bytes:
    request = Request(
        url,
        headers={"User-Agent": "SciGuard-Public-Deployment-Verifier/1.0"},
    )
    tls_context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(request, timeout=15, context=tls_context) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return response.read()


def verify_public_deployment(
    base_url: str,
    *,
    public_root: Path = PUBLIC_ROOT,
    fetch: Callable[[str], bytes] = _download,
) -> list[DeploymentCheck]:
    """Compare public artifacts byte-for-byte and verify referenced shell assets load."""

    normalized_base = base_url.rstrip("/") + "/"
    checks: list[DeploymentCheck] = []
    try:
        html = fetch(normalized_base)
    except (HTTPError, URLError, OSError, RuntimeError) as exc:
        return [
            DeploymentCheck(
                path="/",
                status="FAIL",
                expected_sha256=None,
                observed_sha256=None,
                detail=f"anonymous shell unavailable: {exc}",
            )
        ]

    shell_ok = b"SciGuard Autopilot" in html
    checks.append(
        DeploymentCheck(
            path="/",
            status="PASS" if shell_ok else "FAIL",
            expected_sha256=None,
            observed_sha256=_sha256(html),
            detail=(
                "anonymous Judge shell returned"
                if shell_ok
                else "response is not the SciGuard Judge shell"
            ),
        )
    )

    for raw_asset in sorted(set(ASSET_PATTERN.findall(html))):
        asset_path = raw_asset.decode("utf-8")
        try:
            content = fetch(urljoin(normalized_base, asset_path))
            ok = bool(content)
            detail = f"{len(content)} bytes"
        except (HTTPError, URLError, OSError, RuntimeError) as exc:
            content = b""
            ok = False
            detail = str(exc)
        checks.append(
            DeploymentCheck(
                path=asset_path,
                status="PASS" if ok else "FAIL",
                expected_sha256=None,
                observed_sha256=_sha256(content) if content else None,
                detail=detail,
            )
        )

    for artifact_path in REQUIRED_ARTIFACTS:
        expected = (public_root / artifact_path).read_bytes()
        expected_sha = _sha256(expected)
        try:
            observed = fetch(urljoin(normalized_base, artifact_path))
            observed_sha = _sha256(observed)
            matches = observed == expected
            detail = (
                "public bytes match local release evidence"
                if matches
                else "public artifact is missing, stale, or rewritten"
            )
        except (HTTPError, URLError, OSError, RuntimeError) as exc:
            observed_sha = None
            matches = False
            detail = str(exc)
        checks.append(
            DeploymentCheck(
                path=artifact_path,
                status="PASS" if matches else "FAIL",
                expected_sha256=expected_sha,
                observed_sha256=observed_sha,
                detail=detail,
            )
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify an anonymous SciGuard Judge deployment against web/public."
    )
    parser.add_argument("base_url", help="Anonymous deployment base URL")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the complete machine-readable receipt",
    )
    args = parser.parse_args()
    checks = verify_public_deployment(args.base_url)
    failed = [check for check in checks if check.status != "PASS"]
    if args.json:
        print(
            json.dumps(
                {
                    "base_url": args.base_url.rstrip("/") + "/",
                    "status": "PASS" if not failed else "FAIL",
                    "checks": [asdict(check) for check in checks],
                },
                indent=2,
            )
        )
    else:
        for check in checks:
            print(f"{check.status:4}  {check.path}  {check.detail}")
        print(f"\nDeployment gate: {'PASS' if not failed else 'FAIL'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
