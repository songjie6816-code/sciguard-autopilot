PYTHON ?= python3
DATAHUB ?= datahub
DATAHUB_GMS_URL ?= http://localhost:8080

.PHONY: setup test lint check api datahub-up datahub-sample repair-sandbox repair-replay datahub-live-receipt champion-capture champion-capture-clean verify-public

setup:
	$(PYTHON) -m pip install --upgrade pip wheel setuptools
	$(PYTHON) -m pip install -e '.[api,dev,mcp]'

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

check: lint test

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
champion-capture:
	$(PYTHON) scripts/capture_champion_run.py

champion-capture-clean:
	$(PYTHON) scripts/capture_champion_run.py --require-clean

verify-public:
	@test -n "$(URL)" || (echo "Usage: make verify-public URL=https://judge.example" && exit 2)
	$(PYTHON) scripts/verify_public_deployment.py "$(URL)"
