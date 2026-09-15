#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 09: Deploy Apache Flink Cluster & Expose Dashboard Route
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_DIR="${SCRIPT_DIR}/../manifests"

echo "=== [Step 09] Deploying Apache Flink on OpenShift ==="
oc apply -f "${MANIFEST_DIR}/09-flink-cluster.yaml"

echo ""
echo "Waiting for Flink JobManager and TaskManager to be ready..."
oc rollout status deployment/flink-jobmanager -n confluent --timeout=180s
oc rollout status deployment/flink-taskmanager -n confluent --timeout=180s

echo ""
echo "=== Creating Route for Flink Dashboard ==="
if oc get route flink-web -n confluent &>/dev/null; then
  echo "Route 'flink-web' already exists."
else
  oc create route edge flink-web --service=flink-jobmanager --port=ui --insecure-policy=Redirect -n confluent
fi

FLINK_HOST=$(oc get route flink-web -n confluent -o jsonpath='{.spec.host}')
echo ""
echo "=== Flink Cluster Overview ==="
oc get pods -n confluent -l app=flink
echo ""
echo ">>> Flink Web Dashboard available at: https://${FLINK_HOST}"
echo ">>> Step 09 Complete: Flink cluster is ready."
