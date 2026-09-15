#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 06: Schema Registry Testing (Register Schema & Verify via REST API)
# -----------------------------------------------------------------------------

echo "=== [Step 06] Testing Schema Registry REST API ==="

SUBJECT="lab-pageviews-value"
SCHEMA_PAYLOAD='{
  "schema": "{\"type\":\"record\",\"name\":\"PageViewEvent\",\"fields\":[{\"name\":\"viewtime\",\"type\":\"long\"},{\"name\":\"userid\",\"type\":\"string\"},{\"name\":\"pageid\",\"type\":\"string\"}]}"
}'

echo "1. Registering schema for subject '${SUBJECT}'..."
REGISTER_RESPONSE=$(oc exec schemaregistry-0 -n confluent -c schemaregistry -- curl -s -X POST \
  -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data "${SCHEMA_PAYLOAD}" \
  http://localhost:8081/subjects/${SUBJECT}/versions)

echo "Schema Registration response: ${REGISTER_RESPONSE}"

echo ""
echo "2. Fetching all registered subjects..."
oc exec schemaregistry-0 -n confluent -c schemaregistry -- curl -s http://localhost:8081/subjects

echo ""
echo "3. Fetching latest version for '${SUBJECT}'..."
oc exec schemaregistry-0 -n confluent -c schemaregistry -- curl -s http://localhost:8081/subjects/${SUBJECT}/versions/latest

echo ""
echo "4. Creating Kafka topic 'lab-pageviews' so Control Center links the schema..."
oc exec kafka-0 -n confluent -c kafka -- kafka-topics \
  --bootstrap-server kafka:9071 \
  --create --if-not-exists \
  --topic lab-pageviews \
  --partitions 3 \
  --replication-factor 3

echo ""
echo ">>> Step 06 Complete: Schema Registry is fully operational and topic 'lab-pageviews' created."
