#!/usr/bin/env bash
# Universal gate for every MINT step. Fast, offline, free.
# Usage: bash .agent/skills/mint-tester/scripts/run_gate.sh [extra pytest args]
set -euo pipefail
export PATH="$PWD/.venv/Scripts:$PWD/.venv/bin:$PATH"

echo "== ruff =="
ruff check .
ruff format --check .

echo "== mypy =="
mypy src

echo "== pytest (unit, contract, safety, eval; no live/integration/e2e) =="
pytest -m "not live and not integration and not e2e" \
  --maxfail=5 -q \
  --junitxml=test-results/junit.xml \
  --cov=src --cov-report=term-missing --cov-report=xml:test-results/coverage.xml \
  "$@"

echo "GATE: PASS"
