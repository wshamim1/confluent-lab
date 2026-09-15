#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 02: Install Confluent for Kubernetes (CFK) Operator via Helm
# -----------------------------------------------------------------------------

echo "=== [Step 02] Adding and updating Confluent Helm repository ==="
helm repo add confluentinc https://packages.confluent.io/helm
helm repo update confluentinc

echo ""
echo "=== Installing/Upgrading CFK Operator in 'confluent' namespace ==="
helm upgrade --install confluent-operator confluentinc/confluent-for-kubernetes --namespace confluent

echo ""
echo "=== Waiting for CFK Operator Pod to become Ready ==="
oc wait --for=condition=Ready pod -l app.kubernetes.io/name=confluent-operator -n confluent --timeout=180s || oc get pods -n confluent

echo ""
echo "=== Registered Confluent CRDs ==="
oc get crd | grep "platform.confluent.io" || true

echo ""
echo ">>> Step 02 Complete: Confluent Operator is running."
