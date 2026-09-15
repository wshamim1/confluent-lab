#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 04: Expose Control Center via OpenShift Route
# -----------------------------------------------------------------------------

echo "=== [Step 04] Creating Edge Route for Control Center ==="
if oc get route controlcenter -n confluent &>/dev/null; then
  echo "Route 'controlcenter' already exists."
else
  oc create route edge controlcenter --service=controlcenter --port=9021 --insecure-policy=Redirect -n confluent
fi

echo ""
echo "=== Control Center Route Details ==="
oc get route controlcenter -n confluent

ROUTE_HOST=$(oc get route controlcenter -n confluent -o jsonpath='{.spec.host}')
echo ""
echo ">>> Access Confluent Control Center at: https://${ROUTE_HOST}"
