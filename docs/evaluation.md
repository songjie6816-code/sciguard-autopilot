# Evaluation

`evaluation/harness.py` runs a set of hand-labelled metadata-change scenarios
(`evaluation/scenarios.json`) end-to-end against the live DataHub Quickstart and
scores SciGuard against ground truth.

```bash
PYTHONPATH=. python evaluation/harness.py   # writes examples/outputs/evaluation_report.md
```

Each scenario reads a dataset's live "before" state from DataHub, applies a
labelled mutation (unit change, field removal, ...), runs the deterministic loop
and compares the result to ground truth. Metrics:

- change-detection accuracy
- risk-severity accuracy
- false-alarm rate on negative controls (benign changes that must not trigger)
- impacted-entity precision / recall / F1
- owner-notification recall
- model-at-risk tag targeting
- mean latency
- **ablation**: impacted-entity recall with vs without DataHub lineage

The ablation runs two real impact analyses per change site: WITH DataHub
(lineage traversal) and WITHOUT (catalog search only). Both execute against
DataHub — no number is hardcoded. Lineage recovers the exact downstream cone
(precision = recall = 1.0); the search baseline cannot tell dependency direction
and flags upstream/sibling datasets as affected, so its precision is lower.

The harness GATES: `python evaluation/harness.py` exits non-zero if detection,
severity, false-alarm control, or lineage impact regress. `tests/test_evaluation.py`
asserts the gate logic without DataHub and runs the live gate when DataHub is up.

This is a controlled synthetic benchmark. Its purpose is regression safety, the
DataHub ablation, and false-alarm control — not a claim of real-world accuracy.
LLM cost is not measured yet because the current loop is deterministic (no LLM).
