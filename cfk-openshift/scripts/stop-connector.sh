#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Stop / Delete Kafka Connect Connector
# -----------------------------------------------------------------------------

CONNECTOR_NAME=${1:-"postgres-source-customers"}
CONNECT_CLUSTER=${2:-"connect-pg"}
NAMESPACE="confluent"

echo "=== Stopping/Deleting Connector '${CONNECTOR_NAME}' from cluster '${CONNECT_CLUSTER}' in namespace '${NAMESPACE}' ==="

if oc get connector "${CONNECTOR_NAME}" -n "${NAMESPACE}" &>/dev/null; then
  echo "Deleting Connector Custom Resource '${CONNECTOR_NAME}'..."
  oc delete connector "${CONNECTOR_NAME}" -n "${NAMESPACE}"
  echo "Connector CR deleted."
else
  echo "Connector CR '${CONNECTOR_NAME}' not found in Kubernetes."
fi

# Check and verify directly via Connect REST API if pod is running
CONNECT_POD="${CONNECT_CLUSTER}-0"
if oc get pod "${CONNECT_POD}" -n "${NAMESPACE}" &>/dev/null; then
  echo ""
  echo "=== Verifying with Connect REST API on ${CONNECT_POD} ==="
  ACTIVE_CONNECTORS=$(oc exec "${CONNECT_POD}" -n "${NAMESPACE}" -c "${CONNECT_CLUSTER}" -- curl -s http://localhost:8083/connectors || echo "[]")

  if echo "${ACTIVE_CONNECTORS}" | grep -q "${CONNECTOR_NAME}"; then
    echo "Removing '${CONNECTOR_NAME}' via REST API..."
    oc exec "${CONNECT_POD}" -n "${NAMESPACE}" -c "${CONNECT_CLUSTER}" -- curl -s -X DELETE "http://localhost:8083/connectors/${CONNECTOR_NAME}" || true
    echo ""
  fi

  echo "Active Connectors remaining on ${CONNECT_CLUSTER}:"
  oc exec "${CONNECT_POD}" -n "${NAMESPACE}" -c "${CONNECT_CLUSTER}" -- curl -s http://localhost:8083/connectors || true
fi

echo ""
echo ">>> Connector '${CONNECTOR_NAME}' stopped and removed successfully."
