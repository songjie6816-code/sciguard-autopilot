"""Pure scoring helpers for the evaluation harness (no DataHub, fully testable)."""

from __future__ import annotations

from pydantic import BaseModel


class PRF(BaseModel):
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def counts(predicted: set, expected: set) -> PRF:
    """True/false positives/negatives of a predicted set against ground truth."""
    tp = len(predicted & expected)
    return PRF(tp=tp, fp=len(predicted - expected), fn=len(expected - predicted))


def aggregate(prfs: list[PRF]) -> PRF:
    """Micro-average: sum the raw counts, then derive precision/recall."""
    return PRF(
        tp=sum(p.tp for p in prfs),
        fp=sum(p.fp for p in prfs),
        fn=sum(p.fn for p in prfs),
    )
