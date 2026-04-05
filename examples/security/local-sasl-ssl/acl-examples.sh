#!/usr/bin/env bash
set -euo pipefail

# Example ACL commands for a local SASL_SSL setup.
# Requires kafka-acls to be available and admin.properties to be adapted to your environment.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADMIN_CONFIG="$SCRIPT_DIR/admin.properties"

cat <<EOF
Example commands:

# Allow appuser to write to orders.created
kafka-acls --bootstrap-server localhost:9093 \
  --command-config "$ADMIN_CONFIG" \
  --add \
  --allow-principal User:appuser \
  --operation Write \
  --topic orders.created

# Allow appuser to read orders.created
kafka-acls --bootstrap-server localhost:9093 \
  --command-config "$ADMIN_CONFIG" \
  --add \
  --allow-principal User:appuser \
  --operation Read \
  --topic orders.created

# Allow appuser to join a consumer group
kafka-acls --bootstrap-server localhost:9093 \
  --command-config "$ADMIN_CONFIG" \
  --add \
  --allow-principal User:appuser \
  --operation Read \
  --group orders-created-demo
EOF