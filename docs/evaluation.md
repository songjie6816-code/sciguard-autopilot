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

The reviewed golden consists of the human-readable
`examples/outputs/evaluation_report.md` and machine-readable
`examples/outputs/evaluation_report.json`. The same JSON is copied to
`web/public/evidence/evaluation_report.json`, which is the Judge UI's measured source of
truth; the UI must not duplicate these numbers as constants.

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
- **ablation**: exact lineage traversal vs search-only DataHub vs zero-context abstention

The current regression ablation runs three measured arms per change site; no displayed
number is hardcoded:

- `FULL_DATAHUB` traverses directed DataHub lineage and recovers every exact downstream
  cone.
- `SEARCH_ONLY_DATAHUB` queries DataHub catalog search but has no lineage direction. It
  cannot reliably distinguish upstream, sibling, and downstream assets, so it is never
  labelled “without DataHub”.
- `NO_DATAHUB_CONTEXT` receives no backend object, makes zero catalog calls, and abstains
  rather than inventing dependencies or owners. Its precision is reported as N/A because
  it makes zero predictions; recall and exact-cone recovery are both zero.

The curated report currently records 3/3 exact cones for lineage and 0/3 for each
baseline. Lineage scores 100% precision / 100% recall / 100% F1; search-only scores
60% / 100% / 75%; no-DataHub makes zero predictions and records 0% recall. The no-DataHub
result demonstrates the value of catalog context; it is not a claim that abstention is an
operationally useful incident response.

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
