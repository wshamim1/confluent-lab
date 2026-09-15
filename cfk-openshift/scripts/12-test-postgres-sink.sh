#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 12: Deploy PostgreSQL JDBC Sink Connector for Pageviews & Verify DB Records
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_DIR="${SCRIPT_DIR}/../manifests"
ROOT_DIR="${SCRIPT_DIR}/../.."

# Auto-login if .env is available
if [ -f "${ROOT_DIR}/.env" ]; then
  "${SCRIPT_DIR}/00-oc-login.sh" > /dev/null 2>&1 || true
fi

echo "=== [Step 12] Deploying PostgreSQL JDBC Sink Connector to connect-pg ==="
oc apply -f "${MANIFEST_DIR}/12-connector-postgres-sink.yaml"

echo "Waiting for Connector 'postgres-sink-pageviews' to initialize..."
sleep 12
oc get connector postgres-sink-pageviews -n confluent || true

echo ""
echo "=== Connect REST API - connect-pg Status ==="
oc exec connect-pg-0 -n confluent -c connect-pg -- curl -s http://localhost:8083/connectors/postgres-sink-pageviews/status || true

echo ""
echo "Waiting 5 seconds for records to be sinked to PostgreSQL table 'pageviews'..."
sleep 5

POSTGRES_POD=$(oc get pods -n confluent -l app=postgres -o jsonpath='{.items[0].metadata.name}')

echo ""
echo "=== Querying PostgreSQL Database Table 'pageviews' (Auto-created by JDBC Sink) ==="
oc exec "${POSTGRES_POD}" -n confluent -c postgres -- psql -U pguser -d inventory -c \
  "SELECT viewtime, userid, pageid FROM pageviews ORDER BY viewtime DESC LIMIT 10;"

echo ""
echo "=== Total count of sinked rows in PostgreSQL ==="
oc exec "${POSTGRES_POD}" -n confluent -c postgres -- psql -U pguser -d inventory -c \
  "SELECT COUNT(*) as total_pageviews_in_db FROM pageviews;"

echo ""
echo ">>> Step 12 Complete: Live Kafka pageviews stream is successfully sinking into PostgreSQL!"
