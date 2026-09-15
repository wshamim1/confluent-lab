#!/usr/bin/env bash
# cleanup.sh — Remove the test topic and working directory created by run_lab.sh
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   ./cleanup.sh                         # deletes topic 'external-access-test' and /tmp/kafka-ext-test
#   ./cleanup.sh --topic my-topic        # deletes a custom topic name
#   ./cleanup.sh --keep-workdir          # deletes topic but keeps /tmp/kafka-ext-test
#   ./cleanup.sh --dry-run               # show what would be done, without doing it
#
# The script reads BOOTSTRAP, EXTERNAL_HOST, PORT_OFFSET, NUM_BROKERS, and
# CP_VERSION from the environment.  If any are missing, it re-derives them from
# the Kafka custom resource (same auto-discovery as run_lab.sh Exercise 1).
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/lib"

# ── Defaults ──────────────────────────────────────────────────────────────────
NAMESPACE="${NAMESPACE:-confluent}"
TOPIC="${TOPIC:-external-access-test}"
WORKDIR="/tmp/kafka-ext-test"
KEEP_WORKDIR=false
DRY_RUN=false

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace|-n)  NAMESPACE="$2"; shift 2 ;;
    --topic|-t)      TOPIC="$2";     shift 2 ;;
    --keep-workdir)  KEEP_WORKDIR=true; shift ;;
    --dry-run)       DRY_RUN=true;   shift ;;
    --help|-h)
      sed -n '/^# Usage:/,/^$/p' "$0" | grep -v '^$'
      exit 0 ;;
    *) echo "Unknown option: $1 — run with --help for usage." >&2; exit 1 ;;
  esac
done

export NAMESPACE TOPIC WORKDIR

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log_ok()   { echo -e "  ${GREEN}✓${RESET}  $*"; }
log_warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
log_err()  { echo -e "  ${RED}✗${RESET}  $*" >&2; }
log_info() { echo -e "  ${CYAN}→${RESET}  $*"; }
dry()      {
  if [[ "${DRY_RUN}" = true ]]; then
    echo -e "  ${YELLOW}[dry-run]${RESET}  $*"
  else
    eval "$*"
  fi
}

echo ""
echo -e "${BOLD}${CYAN}── Confluent Level 4 Lab Cleanup ───────────────────${RESET}"
echo ""
echo -e "  Topic   : ${TOPIC}"
echo -e "  Workdir : ${WORKDIR}"
[[ "${DRY_RUN}" = true ]] && echo -e "  ${YELLOW}Dry-run mode — no changes will be made.${RESET}"
echo ""

# ── Ensure we have the variables needed for docker + bootstrap ───────────────
# Source ex1 just for auto-discovery; errors are non-fatal here during cleanup
if [[ -z "${BOOTSTRAP:-}" ]]; then
  log_info "BOOTSTRAP not set — re-discovering cluster values..."

  # Minimal colour-helper exports required by ex1_explore.sh
  export RED GREEN YELLOW CYAN BOLD RESET
  export -f log_ok log_warn log_err log_info 2>/dev/null || true

  # Stub the functions ex1 uses from run_lab.sh
  log_step() { echo -e "\n${BOLD}${CYAN}  $1${RESET}"; }
  log_error() { echo -e "  ${RED}✗${RESET}  $*" >&2; }
  export -f log_step log_error 2>/dev/null || true

  # shellcheck disable=SC1091
  source "${LIB_DIR}/ex1_explore.sh"
  run_ex1 2>/dev/null || {
    log_warn "Auto-discovery failed — you may need to set EXTERNAL_HOST, PORT_OFFSET, NUM_BROKERS, CP_VERSION manually."
  }

  # Build BOOTSTRAP from discovered vars
  if [[ -n "${EXTERNAL_HOST:-}" && -n "${PORT_OFFSET:-}" && -n "${NUM_BROKERS:-}" ]]; then
    BOOTSTRAP=""
    for i in $(seq 0 $((NUM_BROKERS - 1))); do
      p=$((PORT_OFFSET + i))
      BOOTSTRAP="${BOOTSTRAP}${BOOTSTRAP:+,}${EXTERNAL_HOST}:${p}"
    done
    export BOOTSTRAP
    log_ok "Bootstrap: ${BOOTSTRAP}"
  fi
fi

# ── Delete the Kafka topic ────────────────────────────────────────────────────
if [[ -n "${BOOTSTRAP:-}" && -n "${CP_VERSION:-}" && -d "${WORKDIR}" ]]; then
  log_info "Deleting topic '${TOPIC}'..."

  local_vol_flag=""
  if command -v getenforce &>/dev/null && [[ "$(getenforce 2>/dev/null)" = "Enforcing" ]]; then
    local_vol_flag=":Z"
  fi

  dry "docker run --rm --network host \
    -v \"${WORKDIR}:/mnt${local_vol_flag}\" \
    confluentinc/cp-kafka:${CP_VERSION} \
    kafka-topics --delete \
      --topic '${TOPIC}' \
      --bootstrap-server '${BOOTSTRAP}' \
      --command-config /mnt/client.properties 2>&1 || true"

  if [[ "${DRY_RUN}" = false ]]; then
    log_ok "Topic '${TOPIC}' deleted (or was already gone)."
  fi
else
  log_warn "Skipping topic deletion: missing BOOTSTRAP, CP_VERSION, or ${WORKDIR}."
  log_warn "Delete the topic manually from Control Center or with:"
  log_warn "  kafka-topics --delete --topic ${TOPIC} --bootstrap-server <servers> --command-config client.properties"
fi

# ── Remove working directory ──────────────────────────────────────────────────
if [[ "${KEEP_WORKDIR}" = false ]]; then
  if [[ -d "${WORKDIR}" ]]; then
    log_info "Removing ${WORKDIR}..."
    dry "rm -rf '${WORKDIR}'"
    [[ "${DRY_RUN}" = false ]] && log_ok "Removed ${WORKDIR}"
  else
    log_info "${WORKDIR} does not exist — nothing to remove."
  fi
else
  log_info "Keeping ${WORKDIR} (--keep-workdir)."
fi

echo ""
log_ok "Cleanup complete."
echo ""
