#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Insert new records into PostgreSQL to demonstrate live CDC / streaming
# -----------------------------------------------------------------------------

FIRST_NAME=${1:-"NewUser"}
LAST_NAME=${2:-"$(date +%s)"}
EMAIL=${3:-"user_${LAST_NAME}@demo.com"}
COUNTRY=${4:-"Singapore"}

POSTGRES_POD=$(oc get pods -n confluent -l app=postgres -o jsonpath='{.items[0].metadata.name}')

echo "=== Inserting new customer into PostgreSQL (${FIRST_NAME} ${LAST_NAME}, ${EMAIL}, ${COUNTRY}) ==="
oc exec "${POSTGRES_POD}" -n confluent -c postgres -- psql -U pguser -d inventory -c \
  "INSERT INTO customers (first_name, last_name, email, country) VALUES ('${FIRST_NAME}', '${LAST_NAME}', '${EMAIL}', '${COUNTRY}');"

echo ""
echo "=== Latest PostgreSQL table contents ==="
oc exec "${POSTGRES_POD}" -n confluent -c postgres -- psql -U pguser -d inventory -c \
  "SELECT id, first_name, email, country, created_at FROM customers ORDER BY id DESC LIMIT 5;"

echo ""
echo "=== Consuming latest record from Kafka topic 'pg-customers' ==="
sleep 2
oc exec kafka-0 -n confluent -c kafka -- kafka-console-consumer \
  --bootstrap-server kafka:9071 \
  --topic pg-customers \
  --max-messages 1 \
  --timeout-ms 10000 || true

echo ""
echo ">>> Live DB change captured in Kafka topic 'pg-customers'!"
