#!/usr/bin/env bash
# lib/ex3_extract.sh — Exercise 3: Extract CA certificate and SASL credentials
# ─────────────────────────────────────────────────────────────────────────────
# Reads two Kubernetes secrets:
#   $TLS_SECRET   → data.ca.crt  (the CA certificate for the broker)
#   $PLAIN_SECRET → data.plain-users.json  (SASL usernames + passwords)
#
# Files written to $WORKDIR:
#   certs/ca.crt      — CA certificate (PEM)
#   plain-users.json  — SASL credentials (kept in /tmp, not in /root)
# ─────────────────────────────────────────────────────────────────────────────

run_ex3() {
  log_step "Exercise 3 — Extract CA certificate and SASL credentials"

  # ── 3a. Create working directory ───────────────────────────────────────────
  # Use /tmp so the Docker non-root user can traverse the path (see troubleshooting)
  log_info "Creating working directory: ${WORKDIR}"
  mkdir -p "${WORKDIR}/certs"
  cd "${WORKDIR}"
  log_ok "Working directory: ${WORKDIR}"

  # ── 3b. Extract CA certificate ─────────────────────────────────────────────
  log_info "Extracting CA certificate from secret '${TLS_SECRET}'..."

  if kubectl get secret -n "${NAMESPACE}" "${TLS_SECRET}" \
       -o jsonpath='{.data.ca\.crt}' 2>/dev/null \
       | base64 -d > certs/ca.crt && [[ -s certs/ca.crt ]]; then
    log_ok "CA certificate written to ${WORKDIR}/certs/ca.crt"
  else
    # Some secrets store it under tls.crt instead
    log_warn "ca.crt not found under data.ca.crt — trying data.tls.crt..."
    if kubectl get secret -n "${NAMESPACE}" "${TLS_SECRET}" \
         -o jsonpath='{.data.tls\.crt}' 2>/dev/null \
         | base64 -d > certs/ca.crt && [[ -s certs/ca.crt ]]; then
      log_ok "CA certificate written to ${WORKDIR}/certs/ca.crt (from tls.crt)"
    else
      log_error "Could not extract CA certificate from secret '${TLS_SECRET}'."
      log_error "Keys in that secret:"
      kubectl get secret -n "${NAMESPACE}" "${TLS_SECRET}" \
        -o jsonpath='{.data}' 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
for k in d: print(f'    {k}')
" || true
      exit 1
    fi
  fi

  # Verify it looks like a valid PEM certificate
  local cert_info
  cert_info=$(openssl x509 -in certs/ca.crt -noout -subject -issuer -dates 2>/dev/null || true)
  if [[ -n "${cert_info}" ]]; then
    echo "${cert_info}" | sed 's/^/    /'
    log_ok "CA certificate is valid PEM"
  else
    log_error "File certs/ca.crt is not a valid PEM certificate."
    exit 1
  fi

  # ── 3c. Extract SASL credentials ───────────────────────────────────────────
  echo ""
  log_info "Extracting SASL credentials from secret '${PLAIN_SECRET}'..."

  local json_key="plain-users.json"
  if kubectl get secret -n "${NAMESPACE}" "${PLAIN_SECRET}" \
       -o jsonpath='{.data.plain-users\.json}' 2>/dev/null \
       | base64 -d > plain-users.json && [[ -s plain-users.json ]]; then
    log_ok "SASL credentials written to ${WORKDIR}/plain-users.json"
  else
    # Try alternate key name used by some CFK versions
    log_warn "plain-users.json not found — trying data.users..."
    if kubectl get secret -n "${NAMESPACE}" "${PLAIN_SECRET}" \
         -o jsonpath='{.data.users}' 2>/dev/null \
         | base64 -d > plain-users.json && [[ -s plain-users.json ]]; then
      log_ok "SASL credentials written to ${WORKDIR}/plain-users.json (from data.users)"
    else
      log_error "Could not extract SASL credentials from secret '${PLAIN_SECRET}'."
      log_error "Keys in that secret:"
      kubectl get secret -n "${NAMESPACE}" "${PLAIN_SECRET}" \
        -o jsonpath='{.data}' 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
for k in d: print(f'    {k}')
" || true
      exit 1
    fi
  fi

  # Count users without printing passwords
  local user_count
  user_count=$(python3 -c "import json; d=json.load(open('plain-users.json')); print(len(d))" 2>/dev/null || echo "?")
  log_ok "Credentials file contains ${user_count} user(s) — passwords not printed for security"

  # Set permissions so the file is accessible but not world-writable
  chmod 640 plain-users.json
  chmod 644 certs/ca.crt

  # Export WORKDIR so later exercises can use it without cd-ing themselves
  export WORKDIR
}
