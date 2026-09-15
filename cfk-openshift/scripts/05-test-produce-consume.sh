#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 05: Verify Confluent Platform & Perform End-to-End Test
# -----------------------------------------------------------------------------

TOPIC_NAME=${1:-"lab-test"}
MESSAGE_CONTENT=${2:-"hello confluent from openshift"}

echo "=== [Step 05] Verifying Pod Health ==="
oc get pods -n confluent

echo ""
echo "=== 1. Creating topic '${TOPIC_NAME}' (partitions: 3, rf: 3) ==="
oc exec kafka-0 -n confluent -c kafka -- kafka-topics \
  --bootstrap-server kafka:9071 \
  --create --if-not-exists \
  --topic "${TOPIC_NAME}" \
  --partitions 3 \
  --replication-factor 3

echo ""
echo "=== 2. Producing message: '${MESSAGE_CONTENT}' ==="
oc exec kafka-0 -n confluent -c kafka -- bash -c "echo '${MESSAGE_CONTENT}' | kafka-console-producer --bootstrap-server kafka:9071 --topic ${TOPIC_NAME}"

echo ""
echo "=== 3. Consuming message from topic '${TOPIC_NAME}' ==="
oc exec kafka-0 -n confluent -c kafka -- kafka-console-consumer \
  --bootstrap-server kafka:9071 \
  --topic "${TOPIC_NAME}" \
  --from-beginning \
  --max-messages 1 \
  --timeout-ms 10000

echo ""
echo ">>> Step 05 Complete: End-to-end produce/consume test succeeded!"
