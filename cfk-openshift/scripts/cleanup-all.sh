#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Complete Cleanup / Teardown of Confluent Platform, Flink & Project
# -----------------------------------------------------------------------------

NAMESPACE="confluent"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR}/../.."

# Auto-login if .env is available
if [ -f "${ROOT_DIR}/.env" ]; then
  "${SCRIPT_DIR}/00-oc-login.sh" > /dev/null 2>&1 || true
fi

echo "============================================================"
echo "WARNING: This will completely delete the Confluent project,"
echo "all Confluent CRs, PostgreSQL, Flink, and associated PVCs!"
echo "============================================================"

# Check if running interactively or with force flag
if [ "${1:-}" != "--force" ] && [ "${1:-}" != "-f" ]; then
  read -r -p "Are you sure you want to proceed with full cleanup? (y/N): " CONFIRM
  if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Cleanup aborted."
    exit 0
  fi
fi

echo ""
echo "1. Deleting all Connectors..."
oc delete connector --all -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "2. Deleting Control Center..."
oc delete controlcenter --all -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "3. Deleting Kafka REST Proxy..."
oc delete kafkarestproxy --all -n "${NAMESPACE}" --ignore-not-found=true
oc delete kafkarestclass --all -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "4. Deleting ksqlDB..."
oc delete ksqldb --all -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "5. Deleting Connect Clusters..."
oc delete connect --all -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "6. Deleting Schema Registry..."
oc delete schemaregistry --all -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "7. Deleting Kafka Brokers..."
oc delete kafka --all -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "8. Deleting KRaft Controllers..."
oc delete kraftcontroller --all -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "9. Deleting Flink & PostgreSQL Deployments / Services / ConfigMaps..."
oc delete deployment flink-jobmanager flink-taskmanager postgres -n "${NAMESPACE}" --ignore-not-found=true
oc delete service flink-jobmanager postgres -n "${NAMESPACE}" --ignore-not-found=true
oc delete configmap flink-config -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "10. Deleting OpenShift Routes..."
oc delete route controlcenter flink-web schemaregistry -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "11. Uninstalling Confluent Operator Helm Release..."
helm uninstall confluent-operator --namespace "${NAMESPACE}" 2>/dev/null || true

echo ""
echo "12. Deleting all Persistent Volume Claims (PVCs)..."
oc delete pvc --all -n "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "13. Deleting 'confluent' project / namespace..."
oc delete project "${NAMESPACE}" --ignore-not-found=true

echo ""
echo "============================================================"
echo "Cleanup complete! All resources and the project have been removed."
echo "============================================================"
