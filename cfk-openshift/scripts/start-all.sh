#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Start Lab Workloads (Scale Up Back to Normal)
# -----------------------------------------------------------------------------

NAMESPACE="confluent"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR}/../.."

# Auto-login if .env is available
if [ -f "${ROOT_DIR}/.env" ]; then
  "${SCRIPT_DIR}/00-oc-login.sh" > /dev/null 2>&1 || true
fi

echo "============================================================"
echo "Starting Confluent Platform, Flink & Postgres Workloads"
echo "============================================================"

echo ""
echo "1. Scaling up Kafka Brokers (3 replicas)..."
oc patch kafka kafka -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":3}}' --ignore-not-found=true
oc wait --for=condition=Ready pod -l app=kafka -n "${NAMESPACE}" --timeout=300s || true

echo ""
echo "2. Scaling up Schema Registry..."
oc patch schemaregistry schemaregistry -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":1}}' --ignore-not-found=true

echo ""
echo "3. Scaling up ksqlDB..."
oc patch ksqldb ksqldb -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":1}}' --ignore-not-found=true

echo ""
echo "4. Scaling up Kafka REST Proxy..."
oc patch kafkarestproxy kafkarestproxy -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":1}}' --ignore-not-found=true

echo ""
echo "5. Scaling up Connect Clusters (connect-datagen & connect-pg)..."
oc patch connect connect-datagen -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":1}}' --ignore-not-found=true
oc patch connect connect-pg -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":1}}' --ignore-not-found=true

echo ""
echo "6. Scaling up Control Center..."
oc patch controlcenter controlcenter -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":1}}' --ignore-not-found=true

echo ""
echo "7. Scaling up PostgreSQL Database..."
oc scale deployment postgres --replicas=1 -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "8. Scaling up Flink (JobManager & TaskManager)..."
oc scale deployment flink-jobmanager --replicas=1 -n "${NAMESPACE}" --ignore-not-found=true
oc scale deployment flink-taskmanager --replicas=1 -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "=== Current Pods in '${NAMESPACE}' ==="
oc get pods -n "${NAMESPACE}"

echo ""
echo ">>> Workloads started. Check pod status with: oc get pods -n confluent"
