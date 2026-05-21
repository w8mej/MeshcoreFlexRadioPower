.PHONY: help install dev test lint format clean package

help:
	@echo "Targets:"
	@echo "  install   pip install runtime deps"
	@echo "  dev       pip install runtime + dev deps"
	@echo "  test      run pytest"
	@echo "  lint      ruff lint"
	@echo "  format    ruff format"
	@echo "  clean     remove caches and build artefacts"
	@echo "  package   build a sdist+wheel for distribution"

install:
	pip install -r requirements.txt

dev:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

format:
	ruff format .
	ruff check --fix .

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +

package: clean
	python -m build
