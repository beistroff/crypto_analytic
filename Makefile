# Developer tasks. Create and activate a venv first (python -m venv .venv);
# `make install` installs the package into whichever venv is active.
PYTHON ?= python

.PHONY: install test lint fmt

install:
	$(PYTHON) -m pip install -e ".[ec2,dev]"

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

fmt:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .
