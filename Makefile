# Koto Makefile

PYTHON := python
PIP := pip
PYTEST := pytest
BLACK := black
ISORT := isort
FLAKE8 := flake8

.DEFAULT_GOAL := help

.PHONY: help dev test lint format build clean install pre-commit-install mutation-test test-ai-assistant-smoke test-ai-assistant test-ai-assistant-browser test-ai-assistant-release test-eval test-eval-intent test-eval-exec

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

test-ai-assistant-smoke:  ## Run AI assistant smoke regressions
	$(PYTHON) scripts/run_ai_assistant_flow_tests.py smoke

test-ai-assistant:  ## Run the full non-browser AI assistant regression suite
	$(PYTHON) scripts/run_ai_assistant_flow_tests.py full

test-ai-assistant-browser:  ## Run browser smoke tests for the AI assistant
	$(PYTHON) scripts/run_ai_assistant_flow_tests.py browser

test-ai-assistant-release:  ## Run the AI assistant release suite (includes browser smoke)
	$(PYTHON) scripts/run_ai_assistant_flow_tests.py release

test-eval:  ## Run AI evaluation suite (intent accuracy + execution quality, needs GOOGLE_API_KEY)
	$(PYTEST) tests/evaluation/ -v --tb=short

test-eval-intent:  ## Run intent accuracy evaluation only (needs GOOGLE_API_KEY)
	$(PYTEST) tests/evaluation/test_intent_accuracy.py -v --tb=short

test-eval-exec:  ## Run execution quality evaluation only (needs GOOGLE_API_KEY)
	$(PYTEST) tests/evaluation/test_execution_quality.py -v --tb=short

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

mutation-test:  ## Run mutation testing on security-critical modules
	python -m mutmut run --paths-to-mutate="web/auth.py" --tests-dir=tests/unit/ --runner="python -m pytest tests/unit/test_auth_coverage.py tests/unit/test_security_hardening.py -x -q --no-header --tb=no"
	python -m mutmut results

load-test:  ## Run load tests (requires running Koto server)
	$(PYTHON) -m locust -f tests/load/locustfile.py --headless -u 10 -r 2 --run-time 60s --host http://localhost:5820

clean:  ## Remove build artifacts and caches
	Remove-Item -Recurse -Force dist/ -ErrorAction SilentlyContinue
	Remove-Item -Recurse -Force build/ -ErrorAction SilentlyContinue
	Remove-Item -Recurse -Force .pytest_tmp/ -ErrorAction SilentlyContinue
	Remove-Item -Recurse -Force coverage.xml -ErrorAction SilentlyContinue
