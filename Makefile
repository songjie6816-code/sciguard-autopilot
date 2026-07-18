PYTHON ?= python3
DATAHUB ?= datahub
DATAHUB_GMS_URL ?= http://localhost:8080

.PHONY: setup test lint check datahub-up datahub-sample

setup:
	$(PYTHON) -m pip install --upgrade pip wheel setuptools
	$(PYTHON) -m pip install -e '.[dev]'

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

check: lint test

datahub-up:
	$(DATAHUB) docker quickstart

datahub-sample:
	DATAHUB_GMS_URL=$(DATAHUB_GMS_URL) $(DATAHUB) datapack load showcase-ecommerce
