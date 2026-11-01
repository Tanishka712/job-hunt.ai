#!/usr/bin/env bash
# Post-deploy smoke test. Usage: smoke_test.sh <base-url> <expected-git-sha> [step-endpoint-check...]
set -euo pipefail
BASE="${1:?base url required}"; SHA="${2:?git sha required}"

echo "Waiting for /health ..."
for i in $(seq 1 20); do
  if body=$(curl -fsS --max-time 10 "$BASE/health"); then break; fi
  sleep 6
  [ "$i" = 20 ] && { echo "SMOKE FAIL: /health never became healthy"; exit 1; }
done
echo "health: $body"

ver=$(curl -fsS --max-time 10 "$BASE/version")
echo "version: $ver"
echo "$ver" | grep -q "$SHA" || { echo "SMOKE FAIL: deployed SHA does not match $SHA"; exit 1; }

# Step-specific checks: add lines like  curl -fsS -X POST "$BASE/jobs/ingest" -d @tests/fixtures/ingest.json
echo "SMOKE: PASS"
