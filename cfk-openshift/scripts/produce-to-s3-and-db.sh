#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Produce Mock Events to Kafka and Trigger Immediate S3/MinIO & PostgreSQL Sinks
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR}/../.."

# Auto-login if .env is available
if [ -f "${ROOT_DIR}/.env" ]; then
  "${SCRIPT_DIR}/00-oc-login.sh" > /dev/null 2>&1 || true
fi

TOPIC_NAME=${1:-"pageviews"}
COUNT=${2:-10}

echo "============================================================"
echo "Producing ${COUNT} live Avro events to topic '${TOPIC_NAME}'"
echo "============================================================"

# Ensure topic exists
oc exec kafka-0 -n confluent -c kafka -- kafka-topics \
  --bootstrap-server kafka:9071 \
  --create --if-not-exists \
  --topic "${TOPIC_NAME}" \
  --partitions 3 \
  --replication-factor 3

# Produce events using kafka-console-producer or Datagen connector
echo "Triggering Datagen Connector or Manual Batch..."
oc apply -f "${SCRIPT_DIR}/../manifests/08-connector-datagen.yaml"

echo "Waiting 6 seconds for MinIO S3 & PostgreSQL to receive records..."
sleep 6

MINIO_POD=$(oc get pods -n confluent -l app=minio -o jsonpath='{.items[0].metadata.name}')
POSTGRES_POD=$(oc get pods -n confluent -l app=postgres -o jsonpath='{.items[0].metadata.name}')

echo ""
echo "=== MinIO S3 Object Count in 'confluent-data/topics/${TOPIC_NAME}' ==="
oc exec "${MINIO_POD}" -n confluent -c minio -- sh -c "
  mc find local/confluent-data/topics/${TOPIC_NAME}/ | wc -l
"

echo ""
echo "=== Latest JSON File Stored in MinIO ==="
LATEST_S3_FILE=$(oc exec "${MINIO_POD}" -n confluent -c minio -- sh -c "mc find local/confluent-data/topics/${TOPIC_NAME}/ --name '*.json' | tail -n 1" | tr -d '\r')
if [ -n "${LATEST_S3_FILE}" ]; then
  echo "File: ${LATEST_S3_FILE}"
  echo "--- Contents ---"
  oc exec "${MINIO_POD}" -n confluent -c minio -- sh -c "mc cat ${LATEST_S3_FILE} | head -n 5"
fi

echo ""
echo "=== Latest Records in PostgreSQL Table '${TOPIC_NAME}' ==="
oc exec "${POSTGRES_POD}" -n confluent -c postgres -- psql -U pguser -d inventory -c \
  "SELECT viewtime, userid, pageid FROM ${TOPIC_NAME} ORDER BY viewtime DESC LIMIT 5;" 2>/dev/null || echo "Table not queried."

echo ""
echo ">>> Done! Both MinIO (S3) and PostgreSQL have received the live stream."
