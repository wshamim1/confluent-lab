#!/usr/bin/env bash
# run_lab.sh — Confluent Level 4: External Client Access to Confluent Platform on Kubernetes
# ─────────────────────────────────────────────────────────────────────────────────────────────
# Automates all 8 exercises end-to-end:
#   Ex 1  Explore the lab environment (namespace, pods, services, listener config)
#   Ex 2  Verify the external TLS listener and its certificate
#   Ex 3  Extract the CA certificate and SASL credentials from Kubernetes secrets
#   Ex 4  Build the Kafka client.properties file
#   Ex 5  Pull and smoke-test the Confluent Docker image
#   Ex 6  Create a test topic through the external listener
#   Ex 7  Produce and consume a message
#   Ex 8  Print a Control Center verification checklist
#
# Usage:
#   ./run_lab.sh                         # run all exercises (auto-discovers values)
#   ./run_lab.sh --namespace confluent   # override namespace
#   ./run_lab.sh --skip-cleanup          # keep /tmp/kafka-ext-test after the run
#   ./run_lab.sh --topic my-topic        # use a custom topic name
#   ./run_lab.sh --help
#
# Prerequisites (on the TechZone VM):
#   kubectl, openssl, docker, python3
#
# The script discovers EXTERNAL_HOST, PORT_OFFSET, NUM_BROKERS, TLS_SECRET, and
# PLAIN_SECRET automatically from the Kafka custom resource. You can also supply
# them as environment variables before running to skip auto-discovery.
# ─────────────────────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/lib"

# ── Defaults ──────────────────────────────────────────────────────────────────
NAMESPACE="${NAMESPACE:-confluent}"
TOPIC="${TOPIC:-external-access-test}"
WORKDIR="/tmp/kafka-ext-test"
SKIP_CLEANUP=false

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace|-n)  NAMESPACE="$2";  shift 2 ;;
    --topic|-t)      TOPIC="$2";      shift 2 ;;
    --skip-cleanup)  SKIP_CLEANUP=true; shift ;;
    --help|-h)
      sed -n '/^# Usage:/,/^$/p' "$0" | grep -v '^$'
      exit 0 ;;
    *) echo "Unknown option: $1 — run with --help for usage." >&2; exit 1 ;;
  esac
done

export NAMESPACE TOPIC WORKDIR

# ── Colour output helpers ─────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log_step()  { echo -e "\n${BOLD}${CYAN}══════════════════════════════════════════${RESET}"; \
              echo -e "${BOLD}${CYAN}  $1${RESET}"; \
              echo -e "${BOLD}${CYAN}══════════════════════════════════════════${RESET}"; }
log_ok()    { echo -e "  ${GREEN}✓${RESET}  $*"; }
log_warn()  { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
log_error() { echo -e "  ${RED}✗${RESET}  $*" >&2; }
log_info()  { echo -e "  ${CYAN}→${RESET}  $*"; }

export -f log_step log_ok log_warn log_error log_info
export RED GREEN YELLOW CYAN BOLD RESET

# ── Preflight: required tools ─────────────────────────────────────────────────
log_step "Preflight — checking required tools"
MISSING=()
for tool in kubectl openssl docker python3; do
  if command -v "$tool" &>/dev/null; then
    log_ok "$tool  $(command -v "$tool")"
  else
    log_error "$tool  NOT FOUND"
    MISSING+=("$tool")
  fi
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
  log_error "Install missing tools before continuing: ${MISSING[*]}"
  exit 1
fi

# ── Exercise 1: Explore ───────────────────────────────────────────────────────
source "${LIB_DIR}/ex1_explore.sh"
run_ex1

# After ex1, the following vars are exported:
#   EXTERNAL_HOST  PORT_OFFSET  NUM_BROKERS  TLS_SECRET  PLAIN_SECRET  CP_VERSION  KAFKA_POD

# ── Exercise 2: TLS verification ─────────────────────────────────────────────
source "${LIB_DIR}/ex2_tls.sh"
run_ex2

# ── Exercise 3: Extract CA cert + SASL credentials ───────────────────────────
source "${LIB_DIR}/ex3_extract.sh"
run_ex3

# ── Exercise 4: Build client.properties ──────────────────────────────────────
source "${LIB_DIR}/ex4_config.sh"
run_ex4

# ── Exercise 5: Docker smoke-test ────────────────────────────────────────────
source "${LIB_DIR}/ex5_docker.sh"
run_ex5

# ── Exercise 6: Create topic ─────────────────────────────────────────────────
source "${LIB_DIR}/ex6_topic.sh"
run_ex6

# ── Exercise 7: Produce and consume ──────────────────────────────────────────
source "${LIB_DIR}/ex7_produce_consume.sh"
run_ex7

# ── Exercise 8: Control Center checklist ─────────────────────────────────────
source "${LIB_DIR}/ex8_control_center.sh"
run_ex8

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
log_step "Lab Complete ✓"
echo ""
echo -e "  ${BOLD}Topic${RESET}           : ${TOPIC}"
echo -e "  ${BOLD}Bootstrap${RESET}       : ${BOOTSTRAP}"
echo -e "  ${BOLD}Brokers tested${RESET}  : ${NUM_BROKERS}"
echo -e "  ${BOLD}CP Version${RESET}      : ${CP_VERSION}"
echo -e "  ${BOLD}Working dir${RESET}     : ${WORKDIR}"
echo ""
echo -e "  All exercises completed. Review the output above for any warnings."
echo ""

# ── Optional cleanup ─────────────────────────────────────────────────────────
if [[ "${SKIP_CLEANUP}" = false ]]; then
  echo -e "  ${YELLOW}Tip:${RESET} Run ${BOLD}./cleanup.sh${RESET} to delete the topic and remove ${WORKDIR}."
  echo -e "  Or rerun with ${BOLD}--skip-cleanup${RESET} to leave artefacts in place."
fi
