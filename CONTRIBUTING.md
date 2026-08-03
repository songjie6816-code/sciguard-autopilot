# Contributing to SciGuard

SciGuard welcomes focused contributions that strengthen scientific-decision safety, DataHub integration, evidence integrity, or reproducibility.

## Before opening a pull request

1. Open an issue for behavior changes or new domain profiles so the authority boundary and evidence contract can be agreed first.
2. Keep policy decisions deterministic. LLM output may explain a frozen result, but it must not add authority or bypass approval.
3. Label every fixture, sample, snapshot, replay, and live external receipt accurately.
4. Do not commit tokens, unpublished research data, local DataHub URLs, or private repository details.

## Local gate

Use Python 3.10–3.12 and Node.js 22.13+ with Corepack/pnpm:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip wheel setuptools
.venv/bin/python -m pip install -e '.[api,dev,mcp]'
corepack enable
make judge-check PYTHON=.venv/bin/python
```

Pull requests should include tests for new behavior and update the relevant architecture, evidence, or setup documentation. A change to canonical events, receipts, or displayed claims requires a new provenance capture; never hand-edit those artifacts to make a test pass.

## Scope and review

Good contributions are small, reviewable, and preserve the single composition root in `api/runtime.py`. See [docs/code_map.md](docs/code_map.md) for ownership boundaries and [docs/development.md](docs/development.md) for the full DataHub workflow.
