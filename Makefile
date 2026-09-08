# PCB_AI_DESIGNER_V3 — Makefile
.DEFAULT_GOAL := help
SHELL := /bin/bash
PY ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PYV := $(VENV)/bin/python
export PYTHONPATH := $(CURDIR):$(CURDIR)/backend

.PHONY: help setup dev backend frontend worker test test-ai lint format typecheck benchmark docker-up docker-down logs clean

help: ## Affiche l'aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## Installe backend + frontend
	$(PY) -m venv $(VENV)
	$(PIP) install -e ".[dev]"
	cd frontend && npm install

dev: backend frontend-worker ## Démarre backend + frontend + worker

backend: ## API Gateway en mode dev
	$(PYV) -m uvicorn api_gateway.main:app --reload --port 8000

frontend-worker: ## Frontend + worker
	cd frontend && npm run dev &
	$(PYV) -m orchestrator.workflow_engine.runner

worker: ## Worker d'orchestration seul
	$(PYV) -m orchestrator.workflow_engine.runner

test: ## Tests unitaires + intégration
	$(PYV) -m pytest tests/unit tests/integration

test-ai: ## Évaluation des agents IA
	$(PYV) -m pytest tests/ai_evaluation

test-all: ## Tous les tests
	$(PYV) -m pytest tests

lint: ## Ruff check
	$(VENV)/bin/ruff check backend shared tests

format: ## Ruff format
	$(VENV)/bin/ruff format backend shared tests

typecheck: ## Mypy
	$(VENV)/bin/mypy backend/services backend/orchestrator shared

benchmark: ## Benchmarks placement/routage vs Quilter
	$(PYV) -m tests.benchmarks.vs_quilter.runner

docker-up: ## Stack complète Docker
	docker compose up -d --build

docker-down: ## Stop la stack
	docker compose down -v

logs: ## Logs de la stack
	docker compose logs -f --tail=100

clean: ## Nettoie les artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build **/__pycache__
