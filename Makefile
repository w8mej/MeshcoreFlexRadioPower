.PHONY: help venv install dev test lint format clean package

VENV   := .venv
PYTHON := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

help:
	@echo "Targets:"
	@echo "  venv      create .venv virtual environment"
	@echo "  install   pip install runtime deps into .venv"
	@echo "  dev       pip install runtime + dev deps into .venv"
	@echo "  test      run pytest"
	@echo "  lint      ruff lint"
	@echo "  format    ruff format"
	@echo "  clean     remove caches, build artefacts, and .venv"
	@echo "  package   build a sdist+wheel for distribution"

venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

install: venv
	$(PIP) install -r requirements.txt

dev: venv
	$(PIP) install -e ".[dev]"

test:
	$(VENV)/bin/pytest

lint:
	$(VENV)/bin/ruff check .

format:
	$(VENV)/bin/ruff format .
	$(VENV)/bin/ruff check --fix .

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache .coverage htmlcov $(VENV)
	find . -type d -name __pycache__ -exec rm -rf {} +

package: clean
	$(PYTHON) -m build
