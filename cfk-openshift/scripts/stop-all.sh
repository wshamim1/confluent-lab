#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Stop Lab Workloads (Scale Down to 0 Replicas - Preserves PVCs & Configs)
# -----------------------------------------------------------------------------

NAMESPACE="confluent"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR}/../.."

# Auto-login if .env is available
if [ -f "${ROOT_DIR}/.env" ]; then
  "${SCRIPT_DIR}/00-oc-login.sh" > /dev/null 2>&1 || true
fi

echo "============================================================"
echo "Stopping Confluent Platform, Flink & Postgres Workloads"
echo "============================================================"

echo ""
echo "1. Deleting Active Connectors (to prevent stale offset commits)..."
oc delete connector --all -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "2. Scaling down Flink Workloads (JobManager & TaskManager)..."
oc scale deployment flink-jobmanager --replicas=0 -n "${NAMESPACE}" --ignore-not-found=true
oc scale deployment flink-taskmanager --replicas=0 -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "3. Scaling down PostgreSQL Database..."
oc scale deployment postgres --replicas=0 -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "4. Scaling down Connect Clusters (connect-datagen & connect-pg)..."
oc patch connect connect-datagen -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":0}}' --ignore-not-found=true
oc patch connect connect-pg -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":0}}' --ignore-not-found=true

echo ""
echo "5. Scaling down Control Center, REST Proxy, ksqlDB, Schema Registry..."
oc patch controlcenter controlcenter -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":0}}' --ignore-not-found=true
oc patch kafkarestproxy kafkarestproxy -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":0}}' --ignore-not-found=true
oc patch ksqldb ksqldb -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":0}}' --ignore-not-found=true
oc patch schemaregistry schemaregistry -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":0}}' --ignore-not-found=true

echo ""
echo "6. Scaling down Kafka Brokers..."
oc patch kafka kafka -n "${NAMESPACE}" --type merge -p '{"spec":{"replicas":0}}' --ignore-not-found=true

echo ""
echo "7. Note on KRaft Controllers:"
echo "   (KRaft Controller quorum nodes remain at 3 to preserve metadata quorum)."

echo ""
echo "=== Current Pods in '${NAMESPACE}' ==="
oc get pods -n "${NAMESPACE}"

echo ""
echo ">>> All workload pods stopped. Data and PVCs are preserved."
echo ">>> Run './cfk-openshift/scripts/start-all.sh' to start everything back up."
