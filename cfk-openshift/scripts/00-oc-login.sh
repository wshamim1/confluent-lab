#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Step 00: Login to OpenShift Cluster using .env credentials
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR}/../.."

# Load specific OPENSHIFT_* variables safely from .env without executing commands
if [ -f "${ROOT_DIR}/.env" ]; then
  echo "Loading credentials from .env..."
  while IFS='=' read -r key val || [ -n "$key" ]; do
    # Strip leading/trailing whitespace
    key=$(echo "$key" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    case "$key" in
      OPENSHIFT_API_URL|OPENSHIFT_ADMIN_USER|OPENSHIFT_ADMIN_PASSWORD)
        # Strip quotes and carriage returns
        val=$(echo "$val" | sed 's/^[[:space:]]*["'\'']//;s/["'\''][[:space:]]*$//;s/\r$//')
        export "$key"="$val"
        ;;
    esac
  done < "${ROOT_DIR}/.env"
fi

OPENSHIFT_API_URL="${OPENSHIFT_API_URL:-https://api.itz-88y8vv.hub04-lb.techzone.ibm.com:6443}"
OPENSHIFT_ADMIN_USER="${OPENSHIFT_ADMIN_USER:-kubeadmin}"
OPENSHIFT_ADMIN_PASSWORD="${OPENSHIFT_ADMIN_PASSWORD:-}"

if [ -z "${OPENSHIFT_ADMIN_PASSWORD}" ]; then
  echo "Error: OPENSHIFT_ADMIN_PASSWORD is not set in environment or .env file."
  exit 1
fi

echo "=== [Step 00] Logging in to OpenShift API at ${OPENSHIFT_API_URL} ==="
oc login "${OPENSHIFT_API_URL}" \
  -u "${OPENSHIFT_ADMIN_USER}" \
  -p "${OPENSHIFT_ADMIN_PASSWORD}" \
  --insecure-skip-tls-verify=true

echo ""
echo "=== Current active user and project ==="
oc whoami
oc project
