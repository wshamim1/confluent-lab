#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 03: Deploy Confluent Platform Components in sequence
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_DIR="${SCRIPT_DIR}/../manifests"

echo "=== [Step 03] Deploying Confluent Platform CRs ==="

echo "1. Applying KRaft Controller (01-kraftcontroller.yaml)..."
oc apply -f "${MANIFEST_DIR}/01-kraftcontroller.yaml"
echo "Waiting for KRaft Controller pods..."
oc wait --for=condition=Ready pod -l app=kraftcontroller -n confluent --timeout=300s || true

echo ""
echo "2. Applying Kafka Brokers (02-kafka.yaml)..."
oc apply -f "${MANIFEST_DIR}/02-kafka.yaml"
echo "Waiting for Kafka Broker pods..."
oc wait --for=condition=Ready pod -l app=kafka -n confluent --timeout=300s || true

echo ""
echo "3. Applying Schema Registry (03-schemaregistry.yaml)..."
oc apply -f "${MANIFEST_DIR}/03-schemaregistry.yaml"
echo "Waiting for Schema Registry pods..."
oc wait --for=condition=Ready pod -l app=schemaregistry -n confluent --timeout=300s || true

echo ""
echo "4. Applying Kafka Connect (04-connect.yaml)..."
oc apply -f "${MANIFEST_DIR}/04-connect.yaml"
echo "Waiting for Kafka Connect pods..."
oc wait --for=condition=Ready pod -l app=connect -n confluent --timeout=300s || true

echo ""
echo "5. Applying ksqlDB (05-ksqldb.yaml)..."
oc apply -f "${MANIFEST_DIR}/05-ksqldb.yaml"
echo "Waiting for ksqlDB pods..."
oc wait --for=condition=Ready pod -l app=ksqldb -n confluent --timeout=300s || true

echo ""
echo "6. Applying Control Center (06-controlcenter.yaml)..."
oc apply -f "${MANIFEST_DIR}/06-controlcenter.yaml"
echo "Waiting for Control Center pods..."
oc wait --for=condition=Ready pod -l app=controlcenter -n confluent --timeout=300s || true

echo ""
echo "7. Applying Kafka REST Proxy & KafkaRestClass (07-kafkarestproxy.yaml)..."
oc apply -f "${MANIFEST_DIR}/07-kafkarestproxy.yaml"
echo "Waiting for Kafka REST Proxy pods..."
oc wait --for=condition=Ready pod -l app=kafkarestproxy -n confluent --timeout=300s || true

echo ""
echo "=== Current Pod Status in 'confluent' namespace ==="
oc get pods -n confluent

echo ""
echo ">>> Step 03 Complete: All manifests applied."
