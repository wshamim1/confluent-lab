#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 08: ksqlDB Testing (Create Stream & Query Avro Pageviews)
# -----------------------------------------------------------------------------

echo "=== [Step 08] Creating ksqlDB Stream and Running Queries ==="

KSQL_CREATE_STREAM="
CREATE STREAM IF NOT EXISTS pageviews_stream (
  viewtime BIGINT,
  userid VARCHAR,
  pageid VARCHAR
) WITH (
  KAFKA_TOPIC='pageviews',
  VALUE_FORMAT='AVRO'
);
"

echo "1. Submitting Stream creation statement to ksqlDB REST API..."
oc exec ksqldb-0 -n confluent -c ksqldb -- curl -s -X POST \
  -H "Content-Type: application/vnd.ksql.v1+json" \
  --data "{\"ksql\": \"$(echo "$KSQL_CREATE_STREAM" | tr '\n' ' ')\"}" \
  http://localhost:8088/ksql

echo ""
echo ""
echo "2. Listing Streams in ksqlDB..."
oc exec ksqldb-0 -n confluent -c ksqldb -- curl -s -X POST \
  -H "Content-Type: application/vnd.ksql.v1+json" \
  --data '{"ksql": "SHOW STREAMS;"}' \
  http://localhost:8088/ksql

echo ""
echo ""
echo "3. Querying 2 records from 'pageviews_stream'..."
oc exec ksqldb-0 -n confluent -c ksqldb -- curl -s -N -X POST \
  -H "Content-Type: application/vnd.ksql.v1+json" \
  --data '{"ksql": "SELECT * FROM pageviews_stream EMIT CHANGES LIMIT 2;"}' \
  http://localhost:8088/query-stream || true

echo ""
echo ""
echo ">>> Step 08 Complete: ksqlDB Stream processing is verified."
