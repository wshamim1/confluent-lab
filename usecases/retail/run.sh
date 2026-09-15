#!/usr/bin/env bash
# Launch the Retail Analytics dashboard on port 8503
set -e
cd "$(dirname "$0")/../.."   # repo root

KAFKA_ENV="${KAFKA_ENV:-onprem}"
export KAFKA_ENV

echo "Starting Retail Analytics dashboard on http://localhost:8503"
.venv/bin/streamlit run usecases/retail/dashboard/app.py \
  --server.port 8503 \
  --browser.gatherUsageStats false
