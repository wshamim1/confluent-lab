#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

podman exec -i ksqldb-cli ksql http://ksqldb-server:8088 < "$SCRIPT_DIR/ksql-demo.sql"