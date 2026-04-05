#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CERT_DIR="$REPO_ROOT/examples/security/local-sasl-ssl/certs"

if [[ ! -f "$CERT_DIR/broker.keystore.jks" || ! -f "$CERT_DIR/client.truststore.jks" ]]; then
  echo "Local certs not found. Generating self-signed assets..."
  "$REPO_ROOT/examples/security/local-sasl-ssl/generate-certs.sh"
fi

cd "$SCRIPT_DIR"
docker compose -f docker-compose.yml -f docker-compose.secure-local.yml --profile secure-local up -d broker schema-registry connect ksqldb-server ksqldb-cli

cat <<'EOF'
Secure local stack started.

Endpoints:
- Secure Kafka listener: localhost:9093
- Schema Registry: http://localhost:8081
- Kafka Connect: http://localhost:8083
- ksqlDB Server: http://localhost:8088

Use the security example files under examples/security/local-sasl-ssl/ for client and admin configs.
EOF