PYTHON ?= python3
DATAHUB ?= datahub
DATAHUB_GMS_URL ?= http://localhost:8080
PNPM ?= pnpm

.PHONY: setup test lint check datahub-evaluation-check judge-check api datahub-up datahub-sample repair-sandbox repair-replay datahub-live-receipt canonical-prepare canonical-capture canonical-capture-clean verify-public

setup:
	$(PYTHON) -m pip install --upgrade pip wheel setuptools
	$(PYTHON) -m pip install -e '.[api,dev,mcp]'

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

check: lint test

# Re-run the three-arm evaluation against a running DataHub GMS.
# Generated files live in a disposable directory; curated evidence is never overwritten.
datahub-evaluation-check:
	@judge_tmp="$$(mktemp -d)"; \
	trap 'rm -rf "$$judge_tmp"' EXIT; \
	$(PYTHON) -m evaluation.harness \
		--output "$$judge_tmp/evaluation_report.md" \
		--json-output "$$judge_tmp/evaluation_report.json" \
		--performance-output "$$judge_tmp/evaluation_performance.md"; \
	cmp "$$judge_tmp/evaluation_report.md" examples/outputs/evaluation_report.md; \
	cmp "$$judge_tmp/evaluation_report.json" examples/outputs/evaluation_report.json

# One command for the evidence, Python, Web, and anonymous Judge contracts.
judge-check: check
	$(PNPM) --dir web install --frozen-lockfile
	$(PNPM) --dir web lint
	$(PNPM) --dir web test

api:
	$(PYTHON) -m uvicorn api.main:app --host 127.0.0.1 --port 8000

datahub-up:
	$(DATAHUB) docker quickstart

datahub-sample:
	DATAHUB_GMS_URL=$(DATAHUB_GMS_URL) $(DATAHUB) datapack load showcase-ecommerce

repair-sandbox:
	$(PYTHON) scripts/bootstrap_repair_sandbox.py

repair-replay:
	$(PYTHON) scripts/capture_repair_action_replay.py

datahub-live-receipt:
	$(PYTHON) scripts/capture_datahub_live_receipt.py

# Primary one-incident Judge evidence. The two targets above are legacy refreshers.
canonical-prepare:
	$(PYTHON) scripts/capture_canonical_run.py --prepare-github

canonical-capture:
	$(PYTHON) scripts/capture_canonical_run.py

canonical-capture-clean:
	$(PYTHON) scripts/capture_canonical_run.py --require-clean

verify-public:
	@test -n "$(URL)" || (echo "Usage: make verify-public URL=https://judge.example" && exit 2)
	$(PYTHON) scripts/verify_public_deployment.py "$(URL)"
