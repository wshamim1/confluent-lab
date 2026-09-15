#!/usr/bin/env bash
# lib/ex1_explore.sh — Exercise 1: Explore the lab environment
# ─────────────────────────────────────────────────────────────
# Discovers and exports:
#   EXTERNAL_HOST  PORT_OFFSET  NUM_BROKERS  TLS_SECRET  PLAIN_SECRET
#   CP_VERSION     KAFKA_POD
#
# All values can be pre-set as env vars before calling run_lab.sh to skip
# auto-discovery (useful when kubectl output format differs between clusters).
# ─────────────────────────────────────────────────────────────────────────────

run_ex1() {
  log_step "Exercise 1 — Explore the lab environment"

  # ── 1a. Confirm kubectl access ──────────────────────────────────────────────
  log_info "kubectl get nodes"
  if ! kubectl get nodes 2>/dev/null | grep -q "Ready\|minikube\|NAME"; then
    log_error "kubectl get nodes returned no ready nodes."
    log_error "Confirm kubectl is configured to reach the TechZone cluster before continuing."
    exit 1
  fi
  kubectl get nodes
  echo ""

  # ── 1b. Namespace confirmation ──────────────────────────────────────────────
  log_info "Verifying namespace '${NAMESPACE}' exists..."
  if ! kubectl get ns "${NAMESPACE}" &>/dev/null; then
    log_warn "Namespace '${NAMESPACE}' not found. Available namespaces:"
    kubectl get ns --no-headers -o custom-columns=NAME:.metadata.name
    log_error "Set NAMESPACE= to the correct value and rerun."
    exit 1
  fi
  log_ok "Namespace: ${NAMESPACE}"

  # ── 1c. Pods and services ───────────────────────────────────────────────────
  echo ""
  log_info "Pods in namespace '${NAMESPACE}':"
  kubectl get pods -n "${NAMESPACE}" --show-labels 2>/dev/null | head -40 || true

  echo ""
  log_info "Services in namespace '${NAMESPACE}':"
  kubectl get svc -n "${NAMESPACE}" 2>/dev/null | head -30 || true

  # ── 1d. Kafka listener configuration ────────────────────────────────────────
  echo ""
  log_info "Kafka custom resource listener configuration:"
  KAFKA_YAML=$(kubectl get kafka -n "${NAMESPACE}" -o yaml 2>/dev/null || true)

  if [[ -z "${KAFKA_YAML}" ]]; then
    log_error "No Kafka custom resource found in namespace '${NAMESPACE}'."
    log_error "Check the namespace and CFK installation before continuing."
    exit 1
  fi

  echo "${KAFKA_YAML}" | grep -A 40 "listeners:" | head -50 || true
  echo ""

  # ── 1e. Auto-discover variables ─────────────────────────────────────────────
  log_info "Auto-discovering listener configuration values..."

  # EXTERNAL_HOST
  if [[ -z "${EXTERNAL_HOST:-}" ]]; then
    EXTERNAL_HOST=$(echo "${KAFKA_YAML}" | python3 -c "
import sys, re
txt = sys.stdin.read()
# staticForPortBasedRouting.host
m = re.search(r'host:\s*([^\s]+)', txt)
print(m.group(1).strip() if m else '')
" 2>/dev/null || true)
    # Fall back: first external IP from LoadBalancer services
    if [[ -z "${EXTERNAL_HOST}" ]]; then
      EXTERNAL_HOST=$(kubectl get svc -n "${NAMESPACE}" -o jsonpath='{.items[*].status.loadBalancer.ingress[0].ip}' 2>/dev/null \
        | tr ' ' '\n' | grep -v '^$' | head -1 || true)
    fi
    if [[ -z "${EXTERNAL_HOST}" ]]; then
      log_error "Could not auto-discover EXTERNAL_HOST."
      log_error "Set: export EXTERNAL_HOST=<your-external-host-or-IP>"
      exit 1
    fi
  fi

  # PORT_OFFSET
  if [[ -z "${PORT_OFFSET:-}" ]]; then
    PORT_OFFSET=$(echo "${KAFKA_YAML}" | python3 -c "
import sys, re
txt = sys.stdin.read()
m = re.search(r'portOffset:\s*(\d+)', txt)
print(m.group(1) if m else '')
" 2>/dev/null || true)
    if [[ -z "${PORT_OFFSET}" ]]; then
      PORT_OFFSET=9094
      log_warn "Could not auto-discover portOffset — defaulting to ${PORT_OFFSET}"
    fi
  fi

  # NUM_BROKERS (from replicas field)
  if [[ -z "${NUM_BROKERS:-}" ]]; then
    NUM_BROKERS=$(echo "${KAFKA_YAML}" | python3 -c "
import sys, re
txt = sys.stdin.read()
m = re.search(r'replicas:\s*(\d+)', txt)
print(m.group(1) if m else '')
" 2>/dev/null || true)
    if [[ -z "${NUM_BROKERS}" ]]; then
      # Count running kafka pods as fallback
      NUM_BROKERS=$(kubectl get pods -n "${NAMESPACE}" --no-headers \
        -l component=kafka 2>/dev/null | grep -c Running || echo 3)
      log_warn "Could not parse replicas from YAML — using pod count: ${NUM_BROKERS}"
    fi
  fi

  # TLS_SECRET
  if [[ -z "${TLS_SECRET:-}" ]]; then
    TLS_SECRET=$(echo "${KAFKA_YAML}" | python3 -c "
import sys, re
txt = sys.stdin.read()
# Look for secretRef under tls:
idx = txt.find('tls:')
if idx == -1:
    print('')
else:
    snippet = txt[idx:idx+300]
    m = re.search(r'secretRef:\s*\n\s*name:\s*(\S+)', snippet)
    if not m:
        m = re.search(r'secretRef:\s*(\S+)', snippet)
    print(m.group(1) if m else '')
" 2>/dev/null || true)
    if [[ -z "${TLS_SECRET}" ]]; then
      log_error "Could not auto-discover TLS_SECRET."
      log_error "Set: export TLS_SECRET=<secret-name>"
      exit 1
    fi
  fi

  # PLAIN_SECRET
  if [[ -z "${PLAIN_SECRET:-}" ]]; then
    PLAIN_SECRET=$(echo "${KAFKA_YAML}" | python3 -c "
import sys, re
txt = sys.stdin.read()
# Look for secretRef under authentication:
idx = txt.find('authentication:')
if idx == -1:
    print('')
else:
    snippet = txt[idx:idx+400]
    m = re.search(r'secretRef:\s*\n\s*name:\s*(\S+)', snippet)
    if not m:
        m = re.search(r'secretRef:\s*(\S+)', snippet)
    print(m.group(1) if m else '')
" 2>/dev/null || true)
    if [[ -z "${PLAIN_SECRET}" ]]; then
      log_error "Could not auto-discover PLAIN_SECRET."
      log_error "Set: export PLAIN_SECRET=<secret-name>"
      exit 1
    fi
  fi

  # CP_VERSION (from the first kafka pod's container image tag)
  if [[ -z "${CP_VERSION:-}" ]]; then
    KAFKA_POD=$(kubectl get pods -n "${NAMESPACE}" --no-headers \
      -l component=kafka 2>/dev/null | awk 'NR==1{print $1}' || true)
    if [[ -z "${KAFKA_POD}" ]]; then
      # Try generic label fallback
      KAFKA_POD=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null \
        | grep "^kafka-" | awk 'NR==1{print $1}' || true)
    fi
    if [[ -n "${KAFKA_POD}" ]]; then
      CP_VERSION=$(kubectl get pod -n "${NAMESPACE}" "${KAFKA_POD}" \
        -o jsonpath='{.spec.containers[0].image}' 2>/dev/null \
        | awk -F: '{print $NF}' || true)
    fi
    if [[ -z "${CP_VERSION:-}" ]]; then
      CP_VERSION="7.6.0"
      log_warn "Could not detect CP_VERSION from pod image — defaulting to ${CP_VERSION}"
    fi
  fi

  export EXTERNAL_HOST PORT_OFFSET NUM_BROKERS TLS_SECRET PLAIN_SECRET CP_VERSION KAFKA_POD

  echo ""
  log_ok "EXTERNAL_HOST  = ${EXTERNAL_HOST}"
  log_ok "PORT_OFFSET    = ${PORT_OFFSET}"
  log_ok "NUM_BROKERS    = ${NUM_BROKERS}"
  log_ok "TLS_SECRET     = ${TLS_SECRET}"
  log_ok "PLAIN_SECRET   = ${PLAIN_SECRET}"
  log_ok "CP_VERSION     = ${CP_VERSION}"
  log_ok "KAFKA_POD      = ${KAFKA_POD:-<not set>}"
}
