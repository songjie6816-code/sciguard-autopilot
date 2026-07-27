# Repair review output

Return:

```yaml
verdict: APPROVE | REVISE | REJECT
bundle_id: ""
commit_sha: ""
evidence_closure: PASS | FAIL
lineage_freshness: PASS | FAIL | UNKNOWN
root_cause_fit: PASS | FAIL
checks:
  contract: PASS | FAIL | MISSING
  decision_regression: PASS | FAIL | MISSING
  preserved_paths: PASS | FAIL | MISSING
rollback: PASS | FAIL | MISSING
approval:
  expected_owner_urn: ""
  identity_assurance: ""
  production_authorized: false
external_actions:
  provider: ""
  remote_pr_claimed: false
blocking_findings: []
evidence_ids: []
```

An `APPROVE` verdict requires no blocking findings. Keep production authorization false
unless an authenticated provider receipt proves otherwise.
