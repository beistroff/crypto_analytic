# Developer tasks. Create and activate a venv first (python -m venv .venv);
# `make install` installs the package into whichever venv is active.
PYTHON ?= python

.PHONY: install lock test lint fmt

# constraints.txt pins the exact versions tested together (CI and bootstrap use it too).
install:
	$(PYTHON) -m pip install -c constraints.txt -e ".[ec2,dev]"

# After upgrading packages in the venv and running the tests, re-pin them.
lock:
	$(PYTHON) -m pip freeze --exclude-editable > constraints.txt

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

fmt:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .
