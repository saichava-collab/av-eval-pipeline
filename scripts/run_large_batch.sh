#!/usr/bin/env bash
# Triggers a large evaluation batch (default 10,000 scenario variants) against
# the Python orchestrator, exercising the parallel-ingest path end to end.
#
# Usage: ./scripts/run_large_batch.sh [n_variants] [python_service_url]

set -euo pipefail

N_VARIANTS="${1:-10000}"
PYTHON_URL="${2:-http://localhost:8000}"

echo "Triggering evaluation batch of ${N_VARIANTS} scenario variants against ${PYTHON_URL}..."

curl -s -X POST "${PYTHON_URL}/api/v1/evaluate" \
  -H "Content-Type: application/json" \
  -d "{\"n_variants\": ${N_VARIANTS}, \"export_to_warehouse\": true}" | python3 -m json.tool
