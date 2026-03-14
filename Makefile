# Koto Makefile

PYTHON := python
PIP := pip
PYTEST := pytest
BLACK := black
ISORT := isort
FLAKE8 := flake8

.DEFAULT_GOAL := help

.PHONY: help dev test lint format build clean install pre-commit-install

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies
	$(PIP) install -r config/requirements.txt

dev:  ## Start local development server
	$(PYTHON) src/server.py

test:  ## Run tests with coverage
	$(PYTEST) tests/unit/ tests/integration/ -v --tb=short \
		--cov=app --cov-report=term-missing --cov-report=xml:coverage.xml \
		--cov-fail-under=40

test-full:  ## Run all tests
	$(PYTEST) tests/ -v --tb=short \
		--cov=app --cov-report=term-missing \
		--cov-fail-under=40

lint:  ## Run linters (flake8 + bandit)
	$(FLAKE8) src/ app/ tests/ --max-line-length=100 --extend-ignore=E203,E501,W503
	bandit -r app/ src/ -ll -q --exit-zero

format:  ## Auto-format code (isort + black)
	$(ISORT) --profile black src/ app/ tests/
	$(BLACK) --line-length=100 src/ app/ tests/

build:  ## Build PyInstaller executable
	$(PYTHON) -m PyInstaller koto.spec

pre-commit-install:  ## Install pre-commit hooks
	$(PIP) install pre-commit
	pre-commit install

audit:  ## Scan dependencies for CVEs
	$(PIP) install pip-audit
	pip-audit --desc || true

clean:  ## Remove build artifacts and caches
	Remove-Item -Recurse -Force dist/ -ErrorAction SilentlyContinue
	Remove-Item -Recurse -Force build/ -ErrorAction SilentlyContinue
	Remove-Item -Recurse -Force .pytest_tmp/ -ErrorAction SilentlyContinue
	Remove-Item -Recurse -Force coverage.xml -ErrorAction SilentlyContinue
