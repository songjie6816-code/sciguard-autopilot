# SciGuard Champion Execution Plan

> Status source for the post-P1 upgrade from a verified incident replay to a
> proof-carrying Scientific AI Autopilot. Update a gate only when the cited
> implementation and verification evidence exists.

## North-star acceptance test

Given a pipeline-successful scientific contract change, SciGuard must:

1. detect the change;
2. retrieve decision context from DataHub;
3. prove the affected and preserved field-level paths;
4. block only the unsafe decision;
5. create a reviewable, evidence-bound repair;
6. publish that repair to a real Git provider;
7. execute contract, scientific-regression, and safe-branch CI checks;
8. require the accountable owner to approve high-risk action;
9. authorize recovery only from fresh evidence;
10. resolve the DataHub incident and persist a linked Decision Log.

Every verb must correspond to a real action and an inspectable receipt. Recorded
evidence may back up the live experience but may not be relabelled as live.

## Product surfaces

| surface | primary question | default audience |
|---|---|---|
| Brief | What changed, why does it matter, and what did SciGuard protect? | judge / executive |
| Decision Graph | Which field-to-decision paths are affected or proven safe? | data / ML platform |
| Repair Studio | What code and tests are proposed, and why? | reviewer |
| Verification Lab | Does the repair restore truth without breaking safe work? | ML / scientific owner |
| Audit | Which receipts prove every claim and external action? | technical judge |

The current Command Center becomes the Audit surface. It must no longer be the
first cognitive load presented to a judge.

## Score gates

### Use of DataHub

- [x] Dataset schema, units, ownership, governance, and multi-hop lineage.
- [x] Fine-grained lineage drives selective containment.
- [x] Incident-scoped status write-back with read-modify-write safety.
- [x] Native MLFeature, MLFeatureTable, MLModelGroup, MLModel,
      MLModelDeployment, training-run, and inference-run implementation.
- [x] Runtime resolves native model version, features, jobs, deployment, owner,
      criticality, and expected unit into the Repair Bundle.
- [x] Incident control and recovery state mirror to native model/deployment aspects
      without clobbering features, version, metrics, or deployments.
- [x] Native DataHub Incident raise/update/resolve implementation; append-only notes are
      used when the server schema supports them, with a disclosed status-message fallback.
- [x] Native DataHub Document Decision Log linked directly to supported decision-cone
      entities; deployment/process URNs are preserved in document properties on GMS 1.5.
- [x] Live DataHub read-back receipt for all 19 native entities across seven entity roles.
- [x] Live DataHub receipt for the Incident `ACTIVE → RESOLVED` and published Decision Log.
- [x] One canonical 55-event incident binds the native graph, repair revision,
      application, two fresh recovery executions, Incident resolution, and Decision Log.
- [x] Reusable, validated Agent Skills for impact, repair review, and recovery certification.

### Technical execution

- [x] Deterministic detection, impact, policy, enforcement, and recovery.
- [x] Immutable Event schema and isolated Run Store.
- [x] Provider-neutral Proof-Carrying Repair Bundle.
- [x] Repair proposal API with no fabricated PR receipt.
- [x] Local Git adapter creates a real branch and commit, with idempotency and path checks.
- [x] Local verification adapter executes three locked pytest checks and records output hashes.
- [x] Demo-signed approval binds owner, bundle, verification receipt, and commit revision.
- [x] Recovery API accepts a verified approval receipt ID instead of a boolean override.
- [x] Exact-revision applicator accepts only an approved, clean-repository Git tree,
      materializes it in isolated synthetic staging, and records a canonical tree digest.
- [x] Recovery is locked until `APPLIED` and generates fresh server-owned verification
      evidence for the exact commit; callers cannot submit passing checks.
- [x] Canonical capture runner verifies the full one-incident closure and exports the
      replay, Repair Bundle, manifests, and DataHub receipt as one cross-bound package.
- [x] Dirty-tree, wrong-owner, tampered-receipt, commit mismatch, and unsafe-path tests.
- [x] GitHub Git Data + Pull Requests adapter implements a real branch/commit/PR path,
      strict target binding, patch-context validation, and idempotent receipt recovery.
- [x] GitHub Check Runs adapter binds the latest three hosted results to the exact head SHA.
- [ ] Live public-sandbox GitHub PR and Check Runs receipt.
- [ ] SSO/OIDC authentication upgrades the signed demo receipt to production authorization.
- [ ] Production deployment adapter and independently verifiable production authorization.
- [ ] Retry, concurrent-incident, and partial-outage tests for remote adapters.

### Originality

- [x] Scientific decision failure despite technically successful pipeline.
- [x] Field-level selective containment and explicit safe-branch proof.
- [x] Proof-carrying repair requires evidence closure.
- [x] Derived Scientific Decision Graph joins data, native ML, training/deployment/inference,
      and scientific decision assets.
- [x] Counterfactual Verification Lab renders trusted, contaminated, and verified-repair
      outcomes from executed check receipts.
- [x] DataHub Decision Log makes one incident reusable agent context and contains the
      commit, verification, approval, application, and recovery receipt IDs.

### Real-world usefulness

- [x] Concrete model/report publication controls.
- [x] Owner and criticality are deterministic policy inputs.
- [ ] Real PR review and CI workflow.
- [ ] Airflow/dbt/Kubernetes action adapter interface with one fully proven implementation.
- [ ] Practitioner validation with recorded findings and resulting product changes.
- [ ] Measured review effort, prevented unsafe decisions, selective downtime, and MTTR.

### Submission quality

- [x] Anonymous static replay and integrity verification.
- [x] Inspectable evidence receipts and measured lineage ablation.
- [x] Brief / Operate / Audit progressive disclosure.
- [x] Repair Studio shows patch, artifacts, commit, test, approval, and honesty boundaries.
- [x] One canonical `inc-sciguard-champion` capture replaces the former stitched replay and
      binds all lifecycle receipts to the same incident and event stream.
- [x] Three-arm measured ablation: lineage, search-only DataHub, and zero-call no-DataHub abstention.
- [x] Reviewed machine-readable evaluation JSON is shared by the repository and Judge UI.
- [ ] Live Sandbox is the primary CTA; Verified Replay is secondary.
- [x] Plain-language scientific labels in the Brief and Counterfactual Verification Lab.
- [x] Official-rules submission gate and exact 170-second judge-video cut.
- [ ] Three-minute video, deep-dive video, final README, and clean-machine rehearsal.
- [ ] No stale placeholder, unmeasured score, or future capability phrased as current.

### Open-source bonus

- [x] Implement three portable DataHub Skills with output contracts and repository tests.
- [ ] Publish the three skills to the upstream `datahub-project/datahub-skills` repository.
- [ ] Submit a scientific metadata recipe for units, instruments, protocols, and decisions.
- [ ] Submit at least one upstream DataHub fix, documentation contribution, or RFC.
- [ ] Track public issue/PR links and reviewer feedback in the submission.

## Current implementation slice

### Native Production ML dual projection

`data/synthetic_polymer/native_ml.py` adds native ML semantics without removing
the dataset projection required for field contracts:

```text
cleaned dataset
  -> native MLFeature / MLFeatureTable
  -> training DataProcessInstance
  -> versioned MLModel in MLModelGroup
  -> MLModelDeployment
  -> inference DataProcessInstance
  -> decision-report dataset
```

The two projections cross-reference each other through stable URNs and custom
properties. Unit tests prove that the Tg model consumes the Tg feature while the
durability model does not.

### Proof-Carrying Repair Bundle

`core/repair.py` creates a deterministic, provider-neutral proposal containing:

- fail-closed K-to-degC patch;
- unit-contract test;
- P-204 scientific-decision regression test;
- molecular-weight safe-branch non-regression test;
- rollback plan;
- exact affected and preserved URNs;
- critical approval gate resolved to a DataHub owner;
- evidence closure validation;
- explicit `external_action_receipt = null` until an adapter acts.

The latest live proposal is available at:

```text
GET /api/runs/{incident_id}/repair
```

### Real local action and verification boundary

`core/change_provider.py`, `core/verification.py`, `core/approval.py`, and
`core/application.py` turn the proposal into a real local Git commit, execute the three
generated tests without a shell, sign a commit-bound reviewer decision, and materialize
only that approved Git tree in isolated synthetic staging. The application receipt binds
bundle, commit, tree digest, deployment ID, and environment while explicitly recording
`production_authorized: false`. Recovery then re-runs the locked exact-commit verifier;
caller-supplied check status has no authority. The UI and API preserve the boundary that
this is not a GitHub pull request, production identity, or a production deployment.

`scripts/capture_champion_run.py` executes the entire chain against one local DataHub
incident and one ephemeral Git repository, verifies `APPLIED`, requires two fresh recovery
executions, reads back 19 native entities plus the resolved Incident and final Decision
Log, then exports a 55-event public projection. Only machine-local paths are redacted;
receipt IDs and decision fields remain intact. The checked canonical capture was generated
with `--require-clean` and records `source_worktree_dirty: false` in all three
provenance-bearing artifacts.

### GitHub PR and hosted-check boundary

`core/github_provider.py` materializes the reviewed unified diff against the exact
GitHub base commit, creates blobs/tree/commit/branch through the Git Data API, and opens
one bundle-marked pull request. `core/github_verification.py` accepts only the latest
required Check Runs on that exact head SHA. The sandbox workflow uses read-only contents
permission and exposes three stable check names. These adapters are implemented and tested
against an adversarial transport, but the checked-in public evidence still reports
`remote PR: false` until a real sandbox PR receipt is captured.

## Next execution order

1. Capture a live public-sandbox GitHub PR and hosted Check Runs receipt.
2. Add SSO/OIDC-backed reviewer identity and a production deployment adapter.
3. Add practitioner validation and operational-efficiency measures.
4. Publish reusable DataHub Skills and one upstream contribution.
5. Produce the videos, final judge guide, and submission package.

The canonical 55-event clean-source capture was produced against a real local DataHub
Quickstart GMS `v1.5.0.6` using CLI `1.6.0.15`. It reaches `APPLIED`, executes the fresh
recovery verifier twice, resolves the same native Incident, publishes the final Decision
Log, and reads back all 19 native entities. The browser independently verifies the event,
repair, and DataHub closure bindings before rendering the recorded Judge experience.

## Verification commands

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .

PATH=/path/to/node/bin:/path/to/pnpm/bin:$PATH \
  pnpm --dir web test
```
