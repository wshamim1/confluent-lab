#!/usr/bin/env bash
# setup-datagen.sh
# ─────────────────────────────────────────────────────────────────────────────
# Automates lab steps 41-43:
#   1. List available datagen quickstart schemas (step 41)
#   2. Deploy a datagen connector for a chosen schema (step 42)
#   3. Wait for the Kafka topic to appear, then confirm it in Flink (step 43)
#
# Usage:
#   ./setup-datagen.sh                    # deploy 'users' (default)
#   ./setup-datagen.sh orders             # deploy a specific schema
#   ./setup-datagen.sh --list             # list available schemas only
#
# Requirements: ssh, scp, python3 (for status polling)
# The cflt-vsi-key.pem and kafka-ca.crt files must be in the current directory.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Config (reads from .env if present) ───────────────────────────────────────
if [ -f .env ]; then
  set -a
  # Source only simple KEY=VALUE lines; skip comments, blanks, and
  # lines whose value contains unquoted spaces (e.g. VM_SSH_COMMAND)
  # shellcheck disable=SC1090
  source <(grep -v '^#' .env | grep -v '^$' | grep '^[A-Za-z_][A-Za-z0-9_]*=\S*$')
  set +a
fi

# All values must come from .env — no credentials hardcoded here
VM_IP="${VM_FLOATING_IP:?Missing VM_FLOATING_IP in .env}"
SSH_KEY="${VM_SSH_KEY:-cflt-vsi-key.pem}"
SSH_USER="${VM_SSH_USER:-root}"
CC_URL="${CONTROL_CENTER_URL:?Missing CONTROL_CENTER_URL in .env}"
CC_USER="${CONTROL_CENTER_USERNAME:-admin}"
CC_PASS="${CONTROL_CENTER_PASSWORD:?Missing CONTROL_CENTER_PASSWORD in .env}"
CONNECT_URL="${KAFKA_CONNECT_URL:?Missing KAFKA_CONNECT_URL in .env}"
DATAGEN_SCRIPT="/opt/confluent/scripts/deploy-datagen-connector.sh"

SSH="ssh -i ${SSH_KEY} -o StrictHostKeyChecking=accept-new ${SSH_USER}@${VM_IP}"

# ── Argument handling ─────────────────────────────────────────────────────────
ACTION="deploy"
SCHEMA="users"

case "${1:-}" in
  --list)
    echo "==> Available datagen quickstart schemas:"
    ${SSH} "bash ${DATAGEN_SCRIPT} list"
    exit 0
    ;;
  --stop)
    ACTION="stop"
    SCHEMA="${2:-users}"
    ;;
  --stop-all)
    ACTION="stop-all"
    ;;
  -*)
    echo "Usage: $0 [--list | --stop [SCHEMA] | --stop-all | SCHEMA]"
    exit 1
    ;;
  *)
    SCHEMA="${1:-users}"
    ;;
esac

# ── Stop / delete a connector ─────────────────────────────────────────────────
if [ "${ACTION}" = "stop" ]; then
  CONNECTOR_NAME="datagen-${SCHEMA}-source"
  echo "==> Stopping connector '${CONNECTOR_NAME}'..."
  python3 - <<PYEOF
import requests, urllib3, sys
urllib3.disable_warnings()
url  = "${CONNECT_URL}connectors/${CONNECTOR_NAME}"
auth = ("${CC_USER}", "${CC_PASS}")
r = requests.delete(url, auth=auth, verify=False, timeout=10)
if r.status_code in (204, 200):
    print(f"  ✓ Connector '${CONNECTOR_NAME}' deleted.")
elif r.status_code == 404:
    print(f"  Connector '${CONNECTOR_NAME}' not found (already gone?).")
else:
    print(f"  ✗ Unexpected response: {r.status_code} {r.text[:200]}", file=sys.stderr)
    sys.exit(1)
PYEOF
  exit $?
fi

# ── Stop ALL datagen connectors ───────────────────────────────────────────────
if [ "${ACTION}" = "stop-all" ]; then
  echo "==> Stopping all datagen-*-source connectors..."
  python3 - <<PYEOF
import requests, urllib3, sys
urllib3.disable_warnings()
base_url = "${CONNECT_URL}"
auth     = ("${CC_USER}", "${CC_PASS}")

r = requests.get(f"{base_url}connectors", auth=auth, verify=False, timeout=10)
r.raise_for_status()
all_connectors = r.json()

datagen = [c for c in all_connectors if c.startswith("datagen-")]
if not datagen:
    print("  No datagen connectors found.")
    sys.exit(0)

for name in datagen:
    d = requests.delete(f"{base_url}connectors/{name}", auth=auth, verify=False, timeout=10)
    if d.status_code in (204, 200):
        print(f"  ✓ Deleted: {name}")
    else:
        print(f"  ✗ Failed to delete {name}: {d.status_code}", file=sys.stderr)
PYEOF
  exit $?
fi

# ── Step 41: list schemas for reference ───────────────────────────────────────
echo "==> [Step 41] Available datagen schemas on the VM:"
${SSH} "bash ${DATAGEN_SCRIPT} list"
echo ""

# ── Step 42: deploy the connector ─────────────────────────────────────────────
# Connector name follows the pattern the deploy script uses
CONNECTOR_NAME="datagen-${SCHEMA}-source"

echo "==> [Step 42] Deploying datagen connector for schema: '${SCHEMA}'"

# Check if connector already exists before deploying
EXISTING=$(python3 - <<PYEOF
import requests, urllib3
urllib3.disable_warnings()
try:
    r = requests.get(
        "${CONNECT_URL}connectors/${CONNECTOR_NAME}/status",
        auth=("${CC_USER}", "${CC_PASS}"),
        verify=False, timeout=5
    )
    print("EXISTS" if r.status_code == 200 else "NEW")
except Exception:
    print("NEW")
PYEOF
)

if [ "${EXISTING}" = "EXISTS" ]; then
  echo "  Connector '${CONNECTOR_NAME}' already exists — skipping redeploy."
else
  # Allow non-zero exit (e.g. connector already registered on cluster side)
  ${SSH} "bash ${DATAGEN_SCRIPT} ${SCHEMA}" || true
fi
echo ""

# ── Step 43: poll Kafka Connect until connector is RUNNING ────────────────────
echo "==> [Step 43] Waiting for connector '${CONNECTOR_NAME}' to reach RUNNING state..."

MAX_WAIT=90
INTERVAL=5
ELAPSED=0
STATUS="UNKNOWN"

while [ "${ELAPSED}" -lt "${MAX_WAIT}" ]; do
  STATUS=$(python3 - <<PYEOF
import requests, urllib3
urllib3.disable_warnings()
try:
    r = requests.get(
        "${CONNECT_URL}connectors/${CONNECTOR_NAME}/status",
        auth=("${CC_USER}", "${CC_PASS}"),
        verify=False, timeout=5
    )
    if r.status_code == 200:
        data = r.json()
        state = data.get("connector", {}).get("state", "UNKNOWN")
        # Also show task failures if any
        tasks = data.get("tasks", [])
        failed = [t for t in tasks if t.get("state") == "FAILED"]
        if failed:
            print(f"FAILED ({failed[0].get('trace','')[:80]})")
        else:
            print(state)
    elif r.status_code == 404:
        print("NOT_FOUND")
    else:
        print(f"HTTP_{r.status_code}")
except Exception as e:
    print(f"UNREACHABLE: {e}")
PYEOF
)

  echo "  Connector state: ${STATUS} (${ELAPSED}s elapsed)"

  if [ "${STATUS}" = "RUNNING" ]; then
    echo ""
    echo "  ✓ Connector is RUNNING. Records are being written to topic '${SCHEMA}'."
    break
  fi

  # Stop waiting early on permanent failures
  case "${STATUS}" in
    FAILED*|NOT_FOUND) break ;;
  esac

  sleep "${INTERVAL}"
  ELAPSED=$((ELAPSED + INTERVAL))
done

if [ "${STATUS}" != "RUNNING" ]; then
  echo "  ⚠ Connector '${CONNECTOR_NAME}' did not reach RUNNING (last state: ${STATUS})."
  echo "    Check Control Center: ${CC_URL}"
  echo "    Or list connectors:   python3 explore.py connect"
fi

# ── Flink hint ────────────────────────────────────────────────────────────────
echo ""
echo "==> Next: open your Flink SQL shell and run:"
echo ""
echo "    SHOW TABLES;"
echo ""
echo "    You should see '${SCHEMA}' listed alongside the Connect system tables."
echo ""
echo "    To preview data:"
echo "    SELECT * FROM \`${SCHEMA}\` LIMIT 10;"
echo ""
echo "==> Flink shell command (run from your laptop):"
echo "    confluent logout"
echo "    confluent flink shell \\"
echo "      --url https://${CC_USER}:${CC_PASS}@${VM_IP} \\"
echo "      --environment ${FLINK_ENVIRONMENT:-flink-env} \\"
echo "      --compute-pool ${FLINK_COMPUTE_POOL:-flink-compute-pool} \\"
echo "      --catalog ${FLINK_CATALOG:-flink-catalog} \\"
echo "      --database ${FLINK_DATABASE:-flink-database} \\"
echo "      --certificate-authority-path kafka-ca.crt"
