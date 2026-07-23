# Evaluation

`evaluation/harness.py` runs a set of hand-labelled metadata-change scenarios
(`evaluation/scenarios.json`) end-to-end against the live DataHub Quickstart and
scores SciGuard against ground truth.

```bash
PYTHONPATH=. python evaluation/harness.py
```

The default run writes a deterministic report and a separately labelled,
non-deterministic performance sample under ignored `evaluation/outputs/`. It never
changes a tracked file. Refresh the curated golden only after review:

```bash
PYTHONPATH=. python evaluation/harness.py --update-golden
```

Each scenario reads a dataset's live "before" state from DataHub, applies a
labelled mutation (unit change, field removal, ...), runs the deterministic loop
and compares the result to ground truth. Metrics:

- change-detection accuracy
- risk-severity accuracy
- false-alarm rate on negative controls (benign changes that must not trigger)
- impacted-entity precision / recall / F1
- owner-notification recall
- model control targeting
- non-deterministic mean latency in the separate performance sample
- **ablation**: exact lineage traversal vs search-only DataHub without lineage

The current regression ablation runs two real impact analyses per change site: DataHub
lineage traversal and search-only DataHub without lineage. Both execute against DataHub—no
number is hardcoded. Lineage recovers every exact downstream cone; search cannot reliably
infer dependency direction or find differently named consumers. It is therefore labelled
`SEARCH_ONLY_DATAHUB`, never “without DataHub”. WP9 will add a third
`NO_DATAHUB_CONTEXT` mode whose backend fails on any attempted DataHub call.

The harness GATES: `python evaluation/harness.py` exits non-zero if detection,
severity, false-alarm control, or lineage impact regress. `tests/test_evaluation.py`
asserts the gate logic without DataHub and runs the live gate when DataHub is up.

This is a controlled synthetic benchmark. Its purpose is regression safety, the
DataHub ablation, and false-alarm control — not a claim of real-world accuracy.
Policy and recovery metrics deliberately exclude the optional WP5 narration provider:
the model cannot affect their outputs. WP5 instead has adversarial safety tests for zero
raw rows, prompt/output redaction, schema violations, forged actions, tool allowlisting,
and deterministic fallback. Provider latency and token cost are not benchmarked because
no provider is required or configured for the reproducible competition baseline.
