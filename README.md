# SciGuard

SciGuard is a domain-configurable scientific data and ML trust agent. It uses DataHub
schemas, lineage, ownership, quality signals, governance, and ML metadata to detect
upstream scientific-data changes, find affected models and research outputs, recommend
remediation, and write trusted context back to the catalog.

The first end-to-end demonstration is a synthetic polymer glass-transition temperature
(`Tg`) prediction pipeline. A silent unit change from Celsius to Kelvin is traced through
features, a model, and a research report; SciGuard then records the risk and remediation
context in DataHub.

## Status

This repository is under active development for Build with DataHub: The Agent Hackathon
2026. The current milestone is local DataHub Quickstart plus a reproducible sample-data
load. No confidential or unpublished research data is used.

## Why DataHub

SciGuard relies on DataHub as the context graph connecting scientific datasets, their
schemas and owners, quality signals, derived features, ML models, and research outputs.
Without that graph, a unit or protocol change cannot be turned into reliable multi-hop
impact analysis and accountable remediation.

## Planned workflow

```text
scientific data change
  -> read schema, lineage, ownership, quality and ML context from DataHub
  -> evaluate deterministic domain rules
  -> identify affected datasets, models and research outputs
  -> generate remediation actions
  -> write risk tags and an incident summary back to DataHub
```

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
`datahub` / `datahub`. These credentials are for local development only.

The default local Quickstart used here has metadata-service authentication disabled, so
the sample loader connects directly to GMS and does not create an access token.

See [docs/development.md](docs/development.md) for verified environment details and
troubleshooting notes.

## Repository layout

```text
app/                         demo UI
core/                        change detection, impact and remediation logic
datahub_client/              DataHub metadata readers and writers
domain_profiles/             generic, materials and polymer rules
data/synthetic_polymer/      synthetic, non-confidential demo data
examples/incidents/          incident inputs
examples/outputs/            curated expected outputs
tests/                       automated tests
docs/                        architecture, evaluation and development notes
Makefile                     repeatable local setup and verification commands
```

## License

Apache License 2.0. See [LICENSE](LICENSE).
