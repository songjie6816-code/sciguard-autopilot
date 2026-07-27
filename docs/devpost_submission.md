# Devpost submission draft — SciGuard

> Working draft to paste into Devpost. Fill the bracketed items before submitting.
> Honest by construction: every claim here is backed by the repo.

## Submission checklist (do before submitting)

- [ ] Public GitHub repository (currently local only — push and make public)
- [ ] Apache-2.0 LICENSE present ✅ (already in repo)
- [ ] GitHub About section detects and displays the Apache-2.0 license
- [ ] Anonymous project URL opens from a clean browser with no login or local dependency
- [ ] Public demo video < 3 minutes (YouTube / Vimeo / Youku) — `[add link]`
- [ ] English README and install/test steps ✅
- [ ] Complete the blocking checks in [`SUBMISSION_GATE.md`](SUBMISSION_GATE.md)
- [x] **Substantially uses a required DataHub component — the DataHub MCP Server.**
      Contract, schema, directed lineage, ownership and governance context route through
      real MCP tools with `SCIGUARD_USE_MCP=1`; live tests compare those reads with the SDK.
      Fine-grained lineage and write-back remain explicit SDK fallbacks because the current
      MCP tools do not expose those capabilities.

## Project name

SciGuard

## Elevator pitch (one line)

A DataHub-powered trust agent for scientific ML: a lightweight Sentinel catches silent
contract drift, then one evidence-bound incident workflow traces, selectively contains,
and safely recovers the affected scientific decision path.

## Inspiration

Scientific and ML pipelines break *silently* when upstream data changes. A glass-transition
temperature reported in Kelvin instead of Celsius, a molecular-weight unit that flips
`g/mol` → `kg/mol`, a dropped sample identifier — the numbers stay plausible, nothing errors,
and the model keeps predicting on quietly corrupted inputs. Worse, there is usually no
traceability from raw experiment → cleaned data → features → model → research decision, so
no one can answer "if this changed, what downstream is now wrong, and who owns it?"

## What it does

SciGuard runs one signal → investigate → control → recover workflow, with DataHub as the
context, evidence, and action-state layer:

1. **Detect and triage** schema/unit drift with the lightweight deterministic Sentinel.
2. **Escalate only when necessary** using profile-defined severity and decision-path gates.
3. **Investigate independently** through DataHub reverse lineage and local trusted artifacts.
4. **Prove field impact** so the contaminated branch is stopped and safe work remains live.
5. **Control deterministically** with per-asset `HALT` / `WARN` / `ALLOW` decisions.
6. **Generate a proof-carrying repair** with patch, tests, rollback, native ML context,
   exact evidence closure, and a DataHub-owner approval gate.
7. **Act and verify** by creating a real local Git commit and executing contract,
   scientific-decision, and safe-branch tests against that revision.
8. **Apply exactly what was reviewed** by materializing the approved Git tree in isolated
   synthetic staging and recording its canonical tree digest.
9. **Write and recover safely** with incident-scoped DataHub state and fresh,
   server-owned exact-commit evidence checks.

Demo: firmware v4.2 emits 187 mixed-unit rows in batch B042. Every pipeline succeeds, but
P-204 moves from rank #18 to #1. DataHub field lineage distinguishes the contaminated Tg
model/ranking path from the molecular-weight durability path that should remain available.

## Who it's for

Materials- and chemistry-R&D data scientists, research software engineers, ML-platform
teams, and lab data-management teams — anyone who has to trust a model whose inputs come
from evolving experiments. The value: stop an upstream experimental change from silently
breaking downstream models and research conclusions, and make impact, ownership and
remediation traceable.

## Why this is different

Not a generic DataHub search/chat agent and not a generic data-incident bot. SciGuard is
built around the failure modes specific to *scientific* data — units, instruments and
protocols, sample identity (IDs, `SMILES`), and experiment → feature → model → report
lineage — expressed as configurable domain profiles rather than a hard-coded script.

## How we built it

- Python, with a **deterministic core** (no LLM in the decision path) so results are
  reproducible and testable; Pydantic for structured outputs.
- **DataHub** open-source platform via Docker (Colima) Quickstart. Contract, schema,
  directed lineage, ownership, and governance context go through the **DataHub MCP Server**.
  Live parity tests verify this claimed MCP surface. Fine-grained lineage and write-back
  (tags + incident properties) use an explicit SDK fallback.
- **YAML domain profiles** (`generic → materials → polymer`) so a new scientific domain is a
  config change, not code.
- **Next.js cinematic command center** as the primary judge surface; Streamlit remains the
  emergency fallback. Brief, Operate, and Audit views progressively disclose the decision,
  graph, repair, and receipts;
  **pytest** and a **gated evaluation harness** protect the deterministic core.
- An optional **bounded narration layer** receives only redacted metadata/evidence IDs,
  returns Pydantic-validated internal/public summaries, and has no authority over policy,
  recovery, DataHub writes, or arbitrary tool execution.
- A minimal **FastAPI + SSE event surface** streams the frozen event schema from an
  incident-isolated JSON/JSONL Run Store. **55 immutable events bind one live DataHub
  incident, one exact repair revision, and two fresh recovery-verification executions.**
  The bundle is integrity-checked and globally labelled `RECORDED_REPLAY`, never presented
  as a live run.
- The same `inc-sciguard-champion` execution creates a real `LOCAL_GIT` commit, executes
  three pytest checks, records a demo-signed owner review, applies the exact tree to
  synthetic staging, enforces two clean recovery runs, resolves the native Incident, and
  publishes the final Decision Log.
- Its live DataHub closure receipt reads back 19 native Production ML entities. The public
  repair manifest and bundle cross-bind the event SHA, DataHub receipt digest, lifecycle,
  and receipt IDs before Judge Mode renders them.
- Optional GitHub adapters implement Git Data API branch/commit/PR publication and exact-SHA
  Check Run verification. They are covered by fail-closed transport tests; the current
  public capture does not claim a live remote PR until that external receipt exists.
- The exact-revision application boundary accepts only an `APPROVED` bundle whose change,
  verification, and approval receipts agree on the commit. Its current implementation is
  explicitly `LOCAL_STAGING` / `SCIGUARD_SYNTHETIC_STAGING` /
  `production_authorized: false`, not a production deployment.

## Use of DataHub

- **Schema + units** — units stored as dataset custom properties; the detector diffs them.
- **Multi-hop lineage** — `searchAcrossLineage` recovers the exact downstream impact cone.
- **Field lineage** — proves the anomalous Tg field does not feed the molecular-weight branch.
- **Native Production ML** — linked MLFeature, MLFeatureTable, MLModelGroup, versioned
  MLModel, MLModelDeployment, training-run, and inference-run entities add lifecycle
  semantics while dataset projections retain field-level contracts.
- **Ownership** — each affected entity's owner is resolved so the right people are notified.
- **Governance and model context** — criticality, role, model version and synthetic-data tags
  are queryable metadata used by later policy work.
- **Governance write-back** — incident-scoped `AT_RISK`, `QUARANTINED`, and `RESOLVED`
  controls plus evidence references are written back, read-modify-write so existing metadata
  is preserved.
- **Native Incident + Decision Log** — the runtime raises and resolves a DataHub Incident
  over server-supported dataset projections and publishes a DataHub Document with root
  cause, native ML context, repair state, owner review, and evidence closure. On GMS 1.5,
  process/deployment links that are not valid direct aspect destinations remain explicit
  document properties.
- **Configurable domain profiles** — rules are YAML with an inheritance chain.
- **DataHub MCP Server** — contract and context reads run through the MCP Server's tools
  (`search`, `get_lineage`, `list_schema_fields`, `get_entities`) with
  `SCIGUARD_USE_MCP=1`; live tests verify the claimed MCP read surface against the SDK.
  Field-lineage aspect reads and metadata writes use a disclosed SDK fallback.

## Results (measured)

A gated evaluation harness scores 13 labelled scenarios (9 actionable + 4 negative controls)
against the live catalog and fails on any regression:

- change detection: 100% · risk severity: 100% · false alarms on benign changes: 0%
- impacted-entity precision/recall: 100% / 100% · owner recall: 100% · control targeting: 100%

**Current DataHub ablation (three arms measured, nothing hardcoded):** lineage traversal
recovers every exact cone at 100% precision/recall. The explicitly labelled search-only
DataHub baseline scores 60% precision / 100% recall / 75% F1 and recovers 0/3 exact cones. With
DataHub prohibited, the third arm receives no backend object, makes zero catalog calls,
predicts zero assets, and therefore records 0% recall and 0/3 exact cones. Judge Mode reads
the reviewed `web/public/evidence/evaluation_report.json` rather than hardcoding scores.

## Challenges we ran into

- **Write-backs that quietly delete metadata.** DataHub aspects are replace-on-write; a
  partial write nulls the fields you didn't set. We enforce read-modify-write on the whole
  aspect everywhere.
- **Keeping the evaluation honest.** The catalog-search arm still uses DataHub, so we label
  it search-only rather than “without DataHub”. The measured third arm receives no backend,
  makes zero DataHub calls, and abstains instead of fabricating an impact cone.

## Accomplishments we're proud of

- A measured, defensible DataHub ablation instead of a hand-waved claim.
- Safe, non-destructive write-back to a shared catalog.
- Domain knowledge as configurable profiles, not a hard-coded polymer script.
- A tested LLM capability boundary: zero raw rows, local secret/PII redaction, read-only tool
  allowlisting, and deterministic fallback for malformed or unsafe output.
- A projector-readable command center whose policy, process enforcement, and recovery state
  are rendered from the same immutable events used by the API and replay.
- A Proof-Carrying Repair whose commit, three executed checks, owner review, evidence IDs,
  and honesty boundaries can all be inspected independently.
- An exact-revision `APPLIED` boundary that hashes the synthetic-staging tree and keeps
  production authorization explicitly false.
- A Counterfactual Verification Lab that shows trusted, contaminated, and repaired
  scientific decisions from executed receipts, not a pre-scripted animation.

## What we learned

Trust has to be *verified*, not asserted — the same principle SciGuard applies to data, we
applied to our own code and metrics via adversarial review and a gated evaluation.

## What's next

- Capture a real public-sandbox GitHub PR/check-run receipt from the implemented adapters,
  and add SSO/OIDC-backed production approval; the current local action capture
  deliberately does not claim either external result.
- Re-run the successful 55-event canonical incident with
  `python scripts/capture_champion_run.py --require-clean` whenever the frozen
  implementation changes; the checked capture already records
  `source_worktree_dirty: false`.
- Add domains beyond polymers (battery cycle-life, catalysis) as new profiles.

## Built with

python · datahub · datahub-mcp-server · mcp · fastapi · react · pydantic · git · pytest · yaml

## Links

- Code: `[public GitHub repo URL]`
- Demo video: `[< 3 min video URL]`
