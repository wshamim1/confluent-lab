#!/usr/bin/env bash
# usecases/predictive_maintenance/run.sh
# Launch the Predictive Maintenance dashboard.
#
# Usage:
#   ./usecases/predictive_maintenance/run.sh
#   KAFKA_ENV=cloud ./usecases/predictive_maintenance/run.sh
#
# In a second terminal, start the sensor producer:
#   KAFKA_ENV=onprem python3 usecases/predictive_maintenance/scripts/sensor_producer.py

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

echo "▶  Starting Predictive Maintenance Dashboard …"
echo "   URL:        http://localhost:8501"
echo "   Producer:   KAFKA_ENV=${KAFKA_ENV:-onprem} python3 usecases/predictive_maintenance/scripts/sensor_producer.py"
echo ""

exec "${VENV}/bin/streamlit" run \
    "usecases/predictive_maintenance/dashboard/app.py" \
    --server.port 8501 \
    "$@"
