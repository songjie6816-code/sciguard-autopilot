# Recovery certification output

Return:

```yaml
verdict: AUTHORIZED | LOCKED
incident_urn: ""
decision_log_urn: ""
bundle_id: ""
approved_commit_sha: ""
required_checks:
  - id: ""
    status: PASS | FAIL | MISSING | STALE
    evidence_ids: []
clean_run_count: 0
required_clean_runs: 0
approval:
  receipt_id: null
  approver_urn: null
  identity_assurance: null
  production_authorized: false
datahub_writes:
  incident_status: NOT_WRITTEN
  controlled_assets: []
  native_ml_entities: []
  decision_log_status: NOT_WRITTEN
blocking_reasons: []
```

List observed write receipts only. When the verdict is locked, do not emit resolved/allow writes.
