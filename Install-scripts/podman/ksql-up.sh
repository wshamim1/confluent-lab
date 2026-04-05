#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"
podman compose -f compose.yml up -d broker schema-registry connect ksqldb-server ksqldb-cli control-center

cat <<'EOF'
ksqlDB local stack started with Podman.

Endpoints:
- ksqlDB Server: http://localhost:8088
- Schema Registry: http://localhost:8081
- Kafka Connect: http://localhost:8083
- Control Center: http://localhost:9021
EOF