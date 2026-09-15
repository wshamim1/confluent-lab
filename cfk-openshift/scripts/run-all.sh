#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Run All Lab Steps in sequence
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================================"
echo "Starting Confluent for Kubernetes (CFK) Deployment on OpenShift"
echo "============================================================"

echo ""
echo ">>> STEP 0: Logging in to OpenShift..."
"${SCRIPT_DIR}/00-oc-login.sh"

echo ""
echo ">>> STEP 1: Cluster Preparation & Security Setup..."
"${SCRIPT_DIR}/01-prepare-cluster.sh"

echo ""
echo ">>> STEP 2: Installing CFK Operator via Helm..."
"${SCRIPT_DIR}/02-install-cfk-operator.sh"

echo ""
echo ">>> STEP 3: Deploying Confluent Platform Components..."
"${SCRIPT_DIR}/03-deploy-confluent-platform.sh"

echo ""
echo ">>> STEP 4: Exposing Control Center Route..."
"${SCRIPT_DIR}/04-expose-controlcenter.sh"

echo ""
echo ">>> STEP 5: Testing End-to-End Produce/Consume..."
"${SCRIPT_DIR}/05-test-produce-consume.sh"

echo ""
echo ">>> STEP 6: Testing Schema Registry..."
"${SCRIPT_DIR}/06-test-schema-registry.sh"

echo ""
echo ">>> STEP 7: Deploying and Testing Kafka Connect (Datagen)..."
"${SCRIPT_DIR}/07-test-datagen-connect.sh"

echo ""
echo ">>> STEP 8: Testing ksqlDB Stream Processing..."
"${SCRIPT_DIR}/08-test-ksqldb.sh"

echo ""
echo ">>> STEP 9: Deploying Apache Flink Cluster..."
"${SCRIPT_DIR}/09-deploy-flink.sh"

echo ""
echo ">>> STEP 10: Running Flink SQL Pipeline against Kafka..."
"${SCRIPT_DIR}/10-test-flink-sql.sh"

echo ""
echo "============================================================"
echo "Full Confluent Platform & Flink on OpenShift Complete!"
echo "============================================================"
