#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 01: Connect & Prepare Cluster
# - Checks connection / whoami
# - Displays node sizing and storage classes
# - Enables mastersSchedulable on OpenShift scheduler
# - Creates 'confluent' project
# - Grants 'anyuid' SCC to service accounts in 'confluent' project
# -----------------------------------------------------------------------------

echo "=== [Step 01] Verifying cluster connection ==="
oc whoami
oc get nodes

echo ""
echo "=== Checking node capacity and storage class ==="
oc get nodes -o custom-columns="NAME:.metadata.name,ROLE:.metadata.labels.node-role\.kubernetes\.io/worker,CPU:.status.capacity.cpu,MEM:.status.capacity.memory"
oc get storageclass

echo ""
echo "=== Enabling mastersSchedulable for small / managed clusters ==="
oc patch schedulers.config.openshift.io cluster --type merge --patch '{"spec":{"mastersSchedulable":true}}'

echo ""
echo "=== Creating project 'confluent' (if not exists) ==="
if oc get project confluent &>/dev/null; then
  echo "Project 'confluent' already exists. Switching project context..."
  oc project confluent
else
  oc new-project confluent
fi

echo ""
echo "=== Granting 'anyuid' SCC to service accounts in confluent namespace ==="
oc adm policy add-scc-to-group anyuid system:serviceaccounts:confluent

echo ""
echo "=== Verifying SCC ClusterRoleBinding ==="
oc describe clusterrolebinding system:openshift:scc:anyuid | grep "system:serviceaccounts:confluent" || true

echo ""
echo ">>> Step 01 Complete: Cluster is prepared and project 'confluent' is configured."
