"""Create the explicit local Git repository used by SciGuard's action demo."""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTION_ROOT = ROOT / ".sciguard"
DEFAULT_REPOSITORY = ACTION_ROOT / "repair-sandbox"
KEY_PATH = ACTION_ROOT / "approval-signing-key"


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _safe_target(raw_path: str | None) -> Path:
    target = Path(raw_path).resolve() if raw_path else DEFAULT_REPOSITORY.resolve()
    try:
        target.relative_to(ACTION_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(
            f"repair sandbox must stay inside {ACTION_ROOT.resolve()}"
        ) from exc
    return target


def bootstrap(target: Path) -> tuple[Path, Path]:
    ACTION_ROOT.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not target.is_dir() or _git(target, "rev-parse", "--is-inside-work-tree") != "true":
            raise RuntimeError(f"existing target is not a Git repository: {target}")
        if _git(target, "status", "--porcelain"):
            raise RuntimeError(f"existing repair sandbox is dirty: {target}")
    else:
        shutil.copytree(ROOT / "examples" / "repair_sandbox", target)
        _git(target, "init", "-q", "-b", "main")
        _git(target, "config", "user.name", "SciGuard Local Demo")
        _git(target, "config", "user.email", "sciguard@example.invalid")
        _git(target, "add", "--all")
        _git(target, "commit", "-q", "-m", "baseline scientific normalizer")

    if not KEY_PATH.exists():
        KEY_PATH.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        os.chmod(KEY_PATH, 0o600)
    return target, KEY_PATH


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap the bounded local Git and signed-review action sandbox."
    )
    parser.add_argument(
        "--path",
        help="Target inside .sciguard/ (default: .sciguard/repair-sandbox).",
    )
    args = parser.parse_args()
    repository, key_path = bootstrap(_safe_target(args.path))
    print(f"repair repository: {repository}")
    print(f"approval key:      {key_path} (mode 0600)")
    print()
    print("Launch the API with:")
    print(f"SCIGUARD_REPAIR_REPOSITORY='{repository}' \\")
    print(f"SCIGUARD_APPROVAL_SIGNING_KEY=\"$(< '{key_path}')\" \\")
    print("PYTHONPATH=. .venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000")


if __name__ == "__main__":
    main()
