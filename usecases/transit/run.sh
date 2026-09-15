#!/usr/bin/env bash
# usecases/transit/run.sh — Launch the Transit Live Dashboard.
#
# Usage:
#   ./usecases/transit/run.sh
#   KAFKA_ENV=cloud ./usecases/transit/run.sh
#
# In a second terminal, start the event producer:
#   KAFKA_ENV=onprem python3 usecases/transit/producer.py
#   KAFKA_ENV=onprem python3 usecases/transit/producer.py --inject-delay --route AA-101

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV="${REPO_ROOT}/.venv"

if [[ ! -x "${VENV}/bin/streamlit" ]]; then
    echo "ERROR: .venv not found or streamlit not installed."
    echo "Run:  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Always run from repo root so sys.path.insert(0, ".") resolves auth.py correctly
cd "${REPO_ROOT}"

echo "▶  Starting Transit Dashboard …"
echo "   URL:        http://localhost:8502"
echo "   Producer:   KAFKA_ENV=${KAFKA_ENV:-onprem} python3 usecases/transit/producer.py"
echo ""

exec "${VENV}/bin/streamlit" run \
    "usecases/transit/dashboard/app.py" \
    --server.port 8502 \
    "$@"
