#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 07: Deploy Datagen Connector & Verify Stream in Kafka
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_DIR="${SCRIPT_DIR}/../manifests"

echo "=== [Step 07] Deploying Connect Datagen Cluster (04-connect-datagen.yaml) ==="
oc apply -f "${MANIFEST_DIR}/04-connect-datagen.yaml"

echo "Waiting for Connect Datagen pod to be Ready..."
oc wait --for=condition=Ready pod -l app=connect-datagen -n confluent --timeout=300s || true

echo ""
echo "=== Pre-creating Kafka target topic 'pageviews' ==="
oc exec kafka-0 -n confluent -c kafka -- kafka-topics \
  --bootstrap-server kafka:9071 \
  --create --if-not-exists \
  --topic pageviews \
  --partitions 3 \
  --replication-factor 3

echo ""
echo "=== Deploying Datagen Connector CR (08-connector-datagen.yaml) ==="
oc apply -f "${MANIFEST_DIR}/08-connector-datagen.yaml"

echo "Waiting for Connector 'datagen-pageviews' to initialize..."
sleep 15
oc get connector datagen-pageviews -n confluent || true

echo ""
echo "=== Connect REST API - Active Connectors ==="
oc exec connect-datagen-0 -n confluent -c connect-datagen -- curl -s http://localhost:8083/connectors

echo ""
echo "=== Connect REST API - datagen-pageviews Status ==="
oc exec connect-datagen-0 -n confluent -c connect-datagen -- curl -s http://localhost:8083/connectors/datagen-pageviews/status || true

echo ""
echo "=== Sample records generated in 'pageviews' Kafka topic ==="
oc exec kafka-0 -n confluent -c kafka -- kafka-console-consumer \
  --bootstrap-server kafka:9071 \
  --topic pageviews \
  --from-beginning \
  --max-messages 3 \
  --timeout-ms 20000 || true

echo ""
echo ">>> Step 07 Complete: Kafka Connect Datagen stream is running."
