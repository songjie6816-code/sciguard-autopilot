# SciGuard

**A domain-configurable trust agent for scientific data and ML, powered by DataHub.**
SciGuard uses DataHub's schemas, lineage, ownership and governance to catch a silent
upstream data change, trace every affected model and research output, score the risk with
configurable domain rules, and write trusted context back to the catalog — demonstrated on
a polymer materials R&D pipeline.

Built for **Build with DataHub: The Agent Hackathon 2026**. Apache-2.0. No confidential or
unpublished research data is used — all data is synthetic and reproducible.

## The problem

Scientific and ML pipelines break *silently* when upstream data changes:

- a glass-transition temperature `Tg` is reported in Kelvin instead of Celsius,
- a molecular-weight unit flips `g/mol` → `kg/mol`,
- a sample identifier or `SMILES` column is dropped, an instrument protocol changes.

The numbers stay plausible, so nothing errors. The model keeps predicting, the report keeps
ranking candidates — on quietly corrupted inputs. And there is usually no traceability from
raw experiment → cleaned data → features → model → research decision, so no one can answer
"if this changed, what downstream is now wrong, and who owns it?"

## What SciGuard does

A deterministic loop — sense, decide, act — with DataHub as the context and action layer:

![SciGuard architecture](docs/architecture.svg)

```text
scientific-data change
  → change detector   : diff schema + declared units against DataHub
  → lineage analyzer  : walk multi-hop DataHub lineage to affected models/reports + owners
  → risk engine       : match configurable domain-profile rules → severity
  → remediation       : concrete fix actions + incident report
  → write-back        : model-at-risk tag + incident summary to DataHub (read-modify-write)
```

## Why DataHub — measured, not asserted

DataHub is the lineage graph that connects a raw experiment to the model and report it
silently breaks. Remove it and the impact analysis is impossible. The evaluation runs the
impact step two ways against the same catalog:

| approach | precision | recall | F1 | exact cone |
|---|---|---|---|---|
| **WITH DataHub lineage** | **100%** | **100%** | **100%** | **3/3** |
| WITHOUT DataHub (catalog search) | 75% | 100% | 85.7% | 1/3 |

Catalog search has no sense of direction, so it flags *upstream* datasets as affected;
only lineage recovers the exact downstream cone. Both numbers are produced by real runs.

## Results

`python evaluation/harness.py` scores 13 labelled scenarios (9 actionable + 4 negative
controls) against the live catalog and **fails (non-zero exit) if any metric regresses**:

- change-detection accuracy: **100%**
- risk-severity accuracy: **100%**
- false-alarm rate on benign changes: **0%**
- impacted-entity precision / recall: **100% / 100%**
- owner-notification precision / recall: **100% / 100%**
- model-at-risk tag targeting: **100%**

This is a controlled synthetic benchmark; its purpose is regression safety, false-alarm
control, and the DataHub ablation — not a claim of real-world accuracy.

## How DataHub is used

- **Schema + units** — units live as dataset custom properties; the detector diffs them.
- **Multi-hop lineage** — `searchAcrossLineage` recovers the full downstream impact cone.
- **Ownership** — every affected entity's owner is resolved, so the right people are notified.
- **Governance write-back** — a `model-at-risk` tag and an incident summary are written back,
  always read-modify-write so existing catalog metadata is never clobbered.
- **Configurable domain profiles** — rules are YAML (`generic → materials → polymer`), so a
  new scientific domain is a config change, not a code change.
- **MCP-ready** — the read/write client maps directly onto the DataHub MCP Server tools.

## Demo scenario

A synthetic polymer `Tg` prediction pipeline:

```text
raw_polymer_experiments → cleaned_polymer_dataset → polymer_feature_table
  → tg_prediction_model → candidate_report
```

`Tg`'s unit silently changes Celsius → Kelvin mid-pipeline. SciGuard detects it, finds the
downstream feature table, model and report (and correctly does *not* flag the upstream raw
table, unlike search), scores it CRITICAL, and flags the model in DataHub.

## Local setup

Prerequisites: Python 3.10+, Docker Desktop (or Docker Engine with Compose v2), at least
8 GB memory allocated to Docker, and 13 GB free disk space.

```bash
conda create --prefix ./.venv python=3.11 -y
conda activate "$PWD/.venv"
python -m pip install --upgrade pip wheel setuptools
python -m pip install -e '.[dev]'
cp .env.example .env
datahub docker quickstart
DATAHUB_GMS_URL=http://localhost:8080 datahub datapack load showcase-ecommerce
pytest
```

After activating the environment, the equivalent convenience commands are `make check`,
`make datahub-up`, and `make datahub-sample`.

Open <http://localhost:9002> and sign in with the local Quickstart defaults
`datahub` / `datahub`. These credentials are for local development only. The default local
Quickstart has metadata-service authentication disabled, so the sample loader connects
directly to GMS and does not create an access token.

See [docs/development.md](docs/development.md) for verified environment details.

## Run the demo, incident and evaluation

Seed the synthetic polymer lineage graph into DataHub, then run any of the three entry
points:

```bash
python -m pip install -e '.[app]'                       # adds Streamlit
PYTHONPATH=. python data/synthetic_polymer/generate.py
PYTHONPATH=. python data/synthetic_polymer/ingest_to_datahub.py
PYTHONPATH=. python examples/run_tg_unit_incident.py    # CLI incident + write-back
PYTHONPATH=. python evaluation/harness.py               # metrics + DataHub ablation
PYTHONPATH=. streamlit run app/streamlit_app.py         # interactive demo
```

The web demo lets you pick a scientific-data change and watch SciGuard trace the impact
through DataHub lineage, score the risk, and write a `model-at-risk` tag back to the
catalog. See [docs/evaluation.md](docs/evaluation.md) for the metrics and
[docs/architecture.md](docs/architecture.md) for the design.

## Repository layout

```text
app/                         Streamlit demo UI
core/                        change detection, impact, risk and remediation logic
datahub_client/              DataHub metadata readers and writers
domain_profiles/             generic, materials and polymer rules (YAML)
data/synthetic_polymer/      synthetic data generator + DataHub ingest
evaluation/                  labelled scenarios, metrics and gated harness
examples/                    incident inputs and curated outputs
tests/                       automated tests
docs/                        architecture, evaluation and development notes
```

## License

Apache License 2.0. See [LICENSE](LICENSE).
