#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v oc >/dev/null 2>&1; then
  echo "oc command not found"
  exit 1
fi

oc apply -f "$SCRIPT_DIR/namespace.yaml"
oc project confluent

echo "OpenShift namespace prepared: confluent"
echo "Next steps:"
echo "- install your approved Confluent operator or deployment method"
echo "- provision broker storage"
echo "- expose Schema Registry and Connect with routes if required"