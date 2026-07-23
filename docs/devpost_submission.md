# Devpost submission draft — SciGuard

> Working draft to paste into Devpost. Fill the bracketed items before submitting.
> Honest by construction: every claim here is backed by the repo.

## Submission checklist (do before submitting)

- [ ] Public GitHub repository (currently local only — push and make public)
- [ ] Apache-2.0 LICENSE present ✅ (already in repo)
- [ ] Public demo video < 3 minutes (YouTube / Vimeo / Youku) — `[add link]`
- [ ] English README and install/test steps ✅
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
6. **Write and recover safely** with incident-scoped DataHub state and fresh evidence checks.

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
  emergency fallback;
  **pytest** and a **gated evaluation harness** protect the deterministic core.
- An optional **bounded narration layer** receives only redacted metadata/evidence IDs,
  returns Pydantic-validated internal/public summaries, and has no authority over policy,
  recovery, DataHub writes, or arbitrary tool execution.
- A minimal **FastAPI + SSE event surface** streams the frozen event schema from an
  incident-isolated JSON/JSONL Run Store. **38 immutable events: 35 events reach recovery
  lock, followed by 3 verified recovery events.** The bundle is integrity-checked and
  globally labelled `RECORDED_REPLAY`, never presented as a live run.

## Use of DataHub

- **Schema + units** — units stored as dataset custom properties; the detector diffs them.
- **Multi-hop lineage** — `searchAcrossLineage` recovers the exact downstream impact cone.
- **Field lineage** — proves the anomalous Tg field does not feed the molecular-weight branch.
- **Ownership** — each affected entity's owner is resolved so the right people are notified.
- **Governance and model context** — criticality, role, model version and synthetic-data tags
  are queryable metadata used by later policy work.
- **Governance write-back** — incident-scoped `AT_RISK`, `QUARANTINED`, and `RESOLVED`
  controls plus evidence references are written back, read-modify-write so existing metadata
  is preserved.
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

**Current DataHub ablation (both arms measured, nothing hardcoded):** lineage traversal
recovers every exact cone at 100% precision/recall. The explicitly labelled search-only
DataHub baseline scores 60% precision / 83.3% recall and recovers 0/3 exact cones. WP9 adds
a third real run that performs no DataHub calls.

## Challenges we ran into

- **Write-backs that quietly delete metadata.** DataHub aspects are replace-on-write; a
  partial write nulls the fields you didn't set. We enforce read-modify-write on the whole
  aspect everywhere.
- **Keeping the evaluation honest.** The catalog-search arm still uses DataHub, so we label
  it search-only rather than “without DataHub”; WP9 separately implements a backend that
  forbids all DataHub access.

## Accomplishments we're proud of

- A measured, defensible DataHub ablation instead of a hand-waved claim.
- Safe, non-destructive write-back to a shared catalog.
- Domain knowledge as configurable profiles, not a hard-coded polymer script.
- A tested LLM capability boundary: zero raw rows, local secret/PII redaction, read-only tool
  allowlisting, and deterministic fallback for malformed or unsafe output.
- A projector-readable command center whose policy, process enforcement, and recovery state
  are rendered from the same immutable events used by the API and replay.

## What we learned

Trust has to be *verified*, not asserted — the same principle SciGuard applies to data, we
applied to our own code and metrics via adversarial review and a gated evaluation.

## What's next

- Execute the third, true no-DataHub ablation without inventing a placeholder score.
- Register the model as a native **mlModel** entity to deepen ML-metadata usage.
- Add domains beyond polymers (battery cycle-life, catalysis) as new profiles.

## Built with

python · datahub · datahub-mcp-server · mcp · pydantic · streamlit · docker · pytest · yaml

## Links

- Code: `[public GitHub repo URL]`
- Demo video: `[< 3 min video URL]`
