#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"
podman compose -f compose.yml up -d

cat <<'EOF'
Confluent local stack started with Podman.

Endpoints:
- Kafka: localhost:9092
- Schema Registry: http://localhost:8081
- Kafka Connect: http://localhost:8083
- Control Center: http://localhost:9021
EOF