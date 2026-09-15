#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 10: Run Flink SQL Job on Confluent Kafka Stream
# -----------------------------------------------------------------------------

echo "=== [Step 10] Running Flink SQL Pipeline against Kafka broker ==="

JOBMANAGER_POD=$(oc get pods -n confluent -l app=flink,component=jobmanager -o jsonpath='{.items[0].metadata.name}')

echo "Using Flink JobManager pod: ${JOBMANAGER_POD}"

echo ""
echo "1. Submitting Flink SQL statements to query Kafka topics..."
FLINK_SQL="
CREATE TABLE kafka_lab_test (
  message STRING
) WITH (
  'connector' = 'kafka',
  'topic' = 'lab-test',
  'properties.bootstrap.servers' = 'kafka.confluent.svc.cluster.local:9071',
  'properties.group.id' = 'flink-sql-group',
  'scan.startup.mode' = 'earliest-offset',
  'format' = 'raw'
);

CREATE TABLE print_sink (
  message STRING
) WITH (
  'connector' = 'print'
);

INSERT INTO print_sink SELECT UPPER(message) FROM kafka_lab_test;
"

echo "Executing SQL query with sql-client.sh in JobManager..."
oc exec "${JOBMANAGER_POD}" -n confluent -c jobmanager -- bash -c "
  echo \"${FLINK_SQL}\" > /tmp/query.sql
  /opt/flink/bin/sql-client.sh -f /tmp/query.sql || true
"

echo ""
echo "3. Active Flink Jobs:"
oc exec "${JOBMANAGER_POD}" -n confluent -c jobmanager -- /opt/flink/bin/flink list || true

echo ""
echo ">>> Step 10 Complete: Flink SQL processing stream initialized."
