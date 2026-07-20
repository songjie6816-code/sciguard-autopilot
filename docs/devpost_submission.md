# Devpost submission draft — SciGuard

> Working draft to paste into Devpost. Fill the bracketed items before submitting.
> Honest by construction: every claim here is backed by the repo.

## Submission checklist (do before submitting)

- [ ] Public GitHub repository (currently local only — push and make public)
- [ ] Apache-2.0 LICENSE present ✅ (already in repo)
- [ ] Public demo video < 3 minutes (YouTube / Vimeo / Youku) — `[add link]`
- [ ] English README and install/test steps ✅
- [ ] **BLOCKING — substantially uses a required DataHub component.** Rule 3 requires
      substantial use of one of {DataHub MCP Server, Agent Context Kit, DataHub Skills,
      Analytics Agent}. The project currently uses only the DataHub Python SDK, which is
      **none of these**, so as of now it would **fail the stage-1 Pass/Fail gate**. Do not
      submit until the MCP Server (or another of the four) is actually wired and exercised
      in the demo and evaluation. This is the next work item.

## Project name

SciGuard

## Elevator pitch (one line)

A DataHub-powered trust agent for scientific ML: it catches a silent unit change, traces
every affected downstream model and report through lineage, and writes a `model-at-risk`
tag back to the catalog.

## Inspiration

Scientific and ML pipelines break *silently* when upstream data changes. A glass-transition
temperature reported in Kelvin instead of Celsius, a molecular-weight unit that flips
`g/mol` → `kg/mol`, a dropped sample identifier — the numbers stay plausible, nothing errors,
and the model keeps predicting on quietly corrupted inputs. Worse, there is usually no
traceability from raw experiment → cleaned data → features → model → research decision, so
no one can answer "if this changed, what downstream is now wrong, and who owns it?"

## What it does

SciGuard runs a deterministic sense → decide → act loop, with DataHub as the context and
action layer:

1. **Detect** the change by diffing schema and declared units against DataHub.
2. **Trace** impact by walking multi-hop DataHub lineage to the affected feature tables,
   models and reports — with their owners.
3. **Score** the risk against configurable YAML domain-profile rules.
4. **Remediate** with concrete fix actions and an incident report.
5. **Write back** a `model-at-risk` tag and an incident summary to DataHub — always
   read-modify-write, so existing catalog metadata is never clobbered.

Demo: a synthetic polymer `Tg` prediction pipeline
(`raw → cleaned → features → tg_prediction_model → candidate_report`). `Tg`'s unit silently
changes Celsius → Kelvin. The demo app lets you pick where it lands; for a mid-pipeline
change it finds the downstream feature table, model and report and — unlike a catalog
search — does not flag the upstream raw table, scores it CRITICAL, and flags the model.

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
- **DataHub** open-source platform via Docker (Colima) Quickstart; the Python SDK reads
  schema, per-field units (custom properties), ownership and multi-hop lineage
  (`searchAcrossLineage`), and writes tags and incident properties back.
- **YAML domain profiles** (`generic → materials → polymer`) so a new scientific domain is a
  config change, not code.
- **Streamlit** demo UI; **pytest** (39 tests); a **gated evaluation harness**.

## Use of DataHub

- **Schema + units** — units stored as dataset custom properties; the detector diffs them.
- **Multi-hop lineage** — `searchAcrossLineage` recovers the exact downstream impact cone.
- **Ownership** — each affected entity's owner is resolved so the right people are notified.
- **Governance write-back** — a `model-at-risk` tag and incident summary are written back,
  read-modify-write so existing metadata is preserved.
- **Configurable domain profiles** — rules are YAML with an inheritance chain.
- **MCP Server — NOT YET WIRED (required).** The read/write client is structured to route
  through the DataHub MCP Server, but currently calls the SDK directly. Wiring the MCP
  Server is required to satisfy the mandatory-component rule and is the next work item.

## Results (measured)

A gated evaluation harness scores 13 labelled scenarios (9 actionable + 4 negative controls)
against the live catalog and fails on any regression:

- change detection: 100% · risk severity: 100% · false alarms on benign changes: 0%
- impacted-entity precision/recall: 100% / 100% · owner recall: 100% · tag targeting: 100%

**DataHub ablation (both arms measured, nothing hardcoded):** impact analysis with DataHub
lineage scores precision/recall/F1 = 100% and recovers the exact cone 3/3; a no-lineage
catalog-search baseline scores 75% precision (it flags *upstream* datasets, having no sense
of direction) and recovers the exact cone only 1/3.

## Challenges we ran into

- **Write-backs that quietly delete metadata.** DataHub aspects are replace-on-write; a
  partial write nulls the fields you didn't set. We enforce read-modify-write on the whole
  aspect everywhere.
- **Keeping the evaluation honest.** Adversarial multi-agent review caught an ablation whose
  "without DataHub" arm was hardcoded; we rebuilt it as two real measured runs and added a
  gate that fails when the system regresses.

## Accomplishments we're proud of

- A measured, defensible DataHub ablation instead of a hand-waved claim.
- Safe, non-destructive write-back to a shared catalog.
- Domain knowledge as configurable profiles, not a hard-coded polymer script.

## What we learned

Trust has to be *verified*, not asserted — the same principle SciGuard applies to data, we
applied to our own code and metrics via adversarial review and a gated evaluation.

## What's next

- Wire the **DataHub MCP Server** and an optional LLM layer for natural-language reports.
- Register the model as a native **mlModel** entity to deepen ML-metadata usage.
- Add domains beyond polymers (battery cycle-life, catalysis) as new profiles.

## Built with

python · datahub · pydantic · streamlit · docker · pytest · yaml

## Links

- Code: `[public GitHub repo URL]`
- Demo video: `[< 3 min video URL]`
