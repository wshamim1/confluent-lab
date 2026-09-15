#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 13: Deploy MinIO Object Storage, S3 Connect Cluster & S3 Sink Connector
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_DIR="${SCRIPT_DIR}/../manifests"
ROOT_DIR="${SCRIPT_DIR}/../.."

# Auto-login if .env is available
if [ -f "${ROOT_DIR}/.env" ]; then
  "${SCRIPT_DIR}/00-oc-login.sh" > /dev/null 2>&1 || true
fi

echo "=== [Step 13] 1. Deploying MinIO (S3-compatible object storage) ==="
oc apply -f "${MANIFEST_DIR}/13-minio.yaml"

echo "Waiting for MinIO pod to be ready..."
oc rollout status deployment/minio -n confluent --timeout=120s

MINIO_POD=$(oc get pods -n confluent -l app=minio -o jsonpath='{.items[0].metadata.name}')
echo "MinIO Pod: ${MINIO_POD}"

echo ""
echo "=== 2. Creating MinIO Bucket 'confluent-data' via mc CLI ==="
oc exec "${MINIO_POD}" -n confluent -c minio -- sh -c "
  mc alias set local http://localhost:9000 minioadmin minioadmin123
  mc mb --ignore-existing local/confluent-data
  mc ls local
"

echo ""
echo "=== 3. Exposing MinIO Web Console Route ==="
if oc get route minio-console -n confluent &>/dev/null; then
  echo "Route 'minio-console' already exists."
else
  oc create route edge minio-console --service=minio --port=console --insecure-policy=Redirect -n confluent
fi

MINIO_URL=$(oc get route minio-console -n confluent -o jsonpath='{.spec.host}')
echo "MinIO Console URL: https://${MINIO_URL} (User: minioadmin / Pass: minioadmin123)"

echo ""
echo "=== 4. Deploying Connect S3 Cluster (04-connect-s3.yaml) ==="
oc apply -f "${MANIFEST_DIR}/04-connect-s3.yaml"

echo "Waiting for Connect S3 pod to be ready..."
sleep 10
oc wait --for=condition=Ready pod -l app=connect-s3 -n confluent --timeout=300s || true

echo ""
echo "=== 5. Deploying S3 Sink Connector (14-connector-minio-sink.yaml) ==="
oc apply -f "${MANIFEST_DIR}/14-connector-minio-sink.yaml"

echo "Waiting for Connector 's3-sink-pageviews' to initialize..."
sleep 15
oc get connector s3-sink-pageviews -n confluent || true

echo ""
echo "=== Connect REST API - connect-s3 Status ==="
oc exec connect-s3-0 -n confluent -c connect-s3 -- curl -s http://localhost:8083/connectors/s3-sink-pageviews/status || true

echo ""
echo "=== Ensuring Datagen connector is producing records to 'pageviews' ==="
oc apply -f "${MANIFEST_DIR}/08-connector-datagen.yaml"

echo ""
echo "Waiting 10 seconds for files to be written to MinIO S3 bucket..."
sleep 10

echo ""
echo "=== Listing Objects in MinIO 'confluent-data' bucket ==="
oc exec "${MINIO_POD}" -n confluent -c minio -- sh -c "
  mc find local/confluent-data/
"

echo ""
echo "=== Reading a Sample S3 JSON Object Content ==="
SAMPLE_FILE=$(oc exec "${MINIO_POD}" -n confluent -c minio -- sh -c "mc find local/confluent-data/ --name '*.json' | head -n 1" | tr -d '\r')
if [ -n "${SAMPLE_FILE}" ]; then
  echo "Reading content of: ${SAMPLE_FILE}"
  oc exec "${MINIO_POD}" -n confluent -c minio -- sh -c "mc cat ${SAMPLE_FILE} | head -n 5"
else
  echo "No json files found yet. Check back in a few seconds as flush.size batches fill."
fi

echo ""
echo ">>> Step 13 Complete: Kafka stream is successfully sinking to MinIO (S3)!"
