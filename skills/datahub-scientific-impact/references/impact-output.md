# Scientific impact output

Return:

```yaml
changed_entity:
  urn: ""
  fields: []
  before_contract: {}
  after_contract: {}
query_provenance:
  backend: DATAHUB_MCP | DATAHUB_CLI | DATAHUB_SDK
  fallbacks: []
  truncated: false
affected:
  - urn: ""
    field_path: []
    decision_role: ""
    owner_urns: []
    evidence_ids: []
preserved:
  - urn: ""
    field_proof: ""
    owner_urns: []
    evidence_ids: []
unknown:
  - urn: ""
    reason: ""
decision_boundaries: []
recommended_policy_inputs:
  criticality: {}
  governance: {}
```

Use `unknown` whenever field evidence is incomplete. Include native model and deployment
URNs beside their dataset projections.
