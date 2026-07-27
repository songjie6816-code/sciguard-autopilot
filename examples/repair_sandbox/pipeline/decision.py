"""Minimal, deterministic decision path used by the repair integration checks."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    batch_id: str
    tg_value: float
    tg_unit: str
    mn_g_mol: float
    mw_g_mol: float
    trusted_rank: int


def load_candidates(path: Path) -> tuple[Candidate, ...]:
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(
            Candidate(
                candidate_id=row["candidate_id"],
                batch_id=row["batch_id"],
                tg_value=float(row["tg_value"]),
                tg_unit=row["tg_unit"],
                mn_g_mol=float(row["mn_g_mol"]),
                mw_g_mol=float(row["mw_g_mol"]),
                trusted_rank=int(row["trusted_rank"]),
            )
            for row in csv.DictReader(handle)
        )


def rank_candidates(
    candidates: tuple[Candidate, ...],
    *,
    normalizer: Callable[[float, str], float],
) -> dict[str, int]:
    scored = [
        (candidate.candidate_id, normalizer(candidate.tg_value, candidate.tg_unit))
        for candidate in candidates
    ]
    ordered = sorted(scored, key=lambda item: (-item[1], item[0]))
    return {
        candidate_id: rank
        for rank, (candidate_id, _) in enumerate(ordered, start=1)
    }


def molecular_weight_artifact(candidates: tuple[Candidate, ...]) -> bytes:
    """Render the preserved branch independently of the Tg decision path."""

    rows = [
        {
            "candidate_id": candidate.candidate_id,
            "mn_g_mol": candidate.mn_g_mol,
            "mw_g_mol": candidate.mw_g_mol,
        }
        for candidate in sorted(candidates, key=lambda item: item.candidate_id)
    ]
    return json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def publish_molecular_weight_artifact(
    candidates: tuple[Candidate, ...],
    destination: Path,
) -> str:
    payload = molecular_weight_artifact(candidates)
    destination.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()
