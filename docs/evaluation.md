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

The ablation is the key result: without the lineage graph, downstream models and
reports are invisible, so impacted-entity recall collapses to zero.

This is a controlled synthetic benchmark. Its purpose is regression safety, the
DataHub ablation, and false-alarm control — not a claim of real-world accuracy.
LLM cost is not measured yet because the current loop is deterministic (no LLM).
