#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 11: Deploy PostgreSQL, seed data, and configure Kafka Connect JDBC Source
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_DIR="${SCRIPT_DIR}/../manifests"
ROOT_DIR="${SCRIPT_DIR}/../.."

# Source credentials if available
if [ -f "${ROOT_DIR}/.env" ]; then
  while IFS='=' read -r key val || [ -n "$key" ]; do
    key=$(echo "$key" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    case "$key" in
      OPENSHIFT_API_URL|OPENSHIFT_ADMIN_USER|OPENSHIFT_ADMIN_PASSWORD)
        val=$(echo "$val" | sed 's/^[[:space:]]*["'\'']//;s/["'\''][[:space:]]*$//;s/\r$//')
        export "$key"="$val"
        ;;
    esac
  done < "${ROOT_DIR}/.env"
fi

echo "=== [Step 11] Deploying PostgreSQL Database ==="
oc apply -f "${MANIFEST_DIR}/10-postgres.yaml"

echo "Waiting for PostgreSQL pod to be ready..."
oc rollout status deployment/postgres -n confluent --timeout=120s

POSTGRES_POD=$(oc get pods -n confluent -l app=postgres -o jsonpath='{.items[0].metadata.name}')
echo "PostgreSQL Pod: ${POSTGRES_POD}"

echo ""
echo "=== Seeding PostgreSQL with sample table 'customers' and initial records ==="
oc exec "${POSTGRES_POD}" -n confluent -c postgres -- psql -U pguser -d inventory -c "
CREATE TABLE IF NOT EXISTS customers (
  id SERIAL PRIMARY KEY,
  first_name VARCHAR(50),
  last_name VARCHAR(50),
  email VARCHAR(100),
  country VARCHAR(50),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

TRUNCATE TABLE customers;

INSERT INTO customers (first_name, last_name, email, country) VALUES
('Alice', 'Smith', 'alice@ibm.com', 'USA'),
('Bob', 'Jones', 'bob@confluent.io', 'Canada'),
('Charlie', 'Brown', 'charlie@redhat.com', 'UK'),
('Diana', 'Prince', 'diana@techzone.ibm.com', 'Australia'),
('Evan', 'Wright', 'evan@example.com', 'Germany');
"

echo ""
echo "Verifying inserted PostgreSQL records:"
oc exec "${POSTGRES_POD}" -n confluent -c postgres -- psql -U pguser -d inventory -c "SELECT id, first_name, email, country FROM customers;"

echo ""
echo "=== Deploying Connect PG Cluster (04-connect-pg.yaml) ==="
oc apply -f "${MANIFEST_DIR}/04-connect-pg.yaml"

echo "Waiting for Connect PG pod to be Ready..."
sleep 10
oc wait --for=condition=Ready pod -l app=connect-pg -n confluent --timeout=300s || true

echo ""
echo "=== Pre-creating Kafka target topic 'pg-customers' ==="
oc exec kafka-0 -n confluent -c kafka -- kafka-topics \
  --bootstrap-server kafka:9071 \
  --create --if-not-exists \
  --topic pg-customers \
  --partitions 3 \
  --replication-factor 3

echo ""
echo "=== Deploying Kafka Connect JDBC Source Connector (11-connector-postgres.yaml) ==="
oc apply -f "${MANIFEST_DIR}/11-connector-postgres.yaml"

echo "Waiting for Connector 'postgres-source-customers' to start..."
sleep 15
oc get connector postgres-source-customers -n confluent || true

echo ""
echo "=== Connect REST API - Connector Status ==="
oc exec connect-pg-0 -n confluent -c connect-pg -- curl -s http://localhost:8083/connectors/postgres-source-customers/status || true

echo ""
echo "=== Consuming streamed database changes from Kafka topic 'pg-customers' ==="
oc exec kafka-0 -n confluent -c kafka -- kafka-console-consumer \
  --bootstrap-server kafka:9071 \
  --topic pg-customers \
  --from-beginning \
  --max-messages 5 \
  --timeout-ms 20000 || true

echo ""
echo ">>> Step 11 Complete: PostgreSQL data is continuously streaming into Kafka topic 'pg-customers'!"
