#!/usr/bin/env bash
# lib/ex2_tls.sh — Exercise 2: Verify the external TLS listener
# ─────────────────────────────────────────────────────────────────────────────
# Connects to every broker port with openssl s_client and inspects:
#   - Certificate subject, issuer, and validity dates
#   - Subject Alternative Names (SANs)
#
# Exits non-zero if any broker port is unreachable or returns no certificate.
# A SAN mismatch is a warning, not a hard failure, since the lab instructs the
# student to stop and fix it — the script records the finding and continues so
# the remaining output is still visible.
# ─────────────────────────────────────────────────────────────────────────────

run_ex2() {
  log_step "Exercise 2 — Verify the external TLS listener"

  local all_ok=true

  # ── 2a. Certificate check on each broker port ──────────────────────────────
  log_info "Checking TLS certificate on each broker port..."
  echo ""

  for i in $(seq 0 $((NUM_BROKERS - 1))); do
    local port=$((PORT_OFFSET + i))
    echo -e "  ${BOLD}=== port ${port} (broker ${i}) ===${RESET}"

    local cert_output
    cert_output=$(echo | timeout 5 openssl s_client \
      -connect "${EXTERNAL_HOST}:${port}" \
      -servername "${EXTERNAL_HOST}" 2>/dev/null \
      | openssl x509 -noout -subject -issuer -dates 2>/dev/null || true)

    if [[ -n "${cert_output}" ]]; then
      echo "${cert_output}" | sed 's/^/    /'
      log_ok "Port ${port}: TLS handshake succeeded"
    else
      log_error "Port ${port}: no TLS response or port unreachable"
      all_ok=false
    fi
    echo ""
  done

  if [[ "${all_ok}" = false ]]; then
    log_error "One or more broker ports did not respond."
    log_error "Re-check EXTERNAL_HOST='${EXTERNAL_HOST}', PORT_OFFSET='${PORT_OFFSET}', NUM_BROKERS='${NUM_BROKERS}' before continuing."
    exit 1
  fi

  # ── 2b. Subject Alternative Name check ────────────────────────────────────
  log_info "Checking Subject Alternative Name (SAN) on port ${PORT_OFFSET}..."
  echo ""

  local san_output
  san_output=$(echo | timeout 5 openssl s_client \
    -connect "${EXTERNAL_HOST}:${PORT_OFFSET}" \
    -servername "${EXTERNAL_HOST}" 2>/dev/null \
    | openssl x509 -noout -text 2>/dev/null \
    | grep -A2 "Subject Alternative Name" || true)

  if [[ -n "${san_output}" ]]; then
    echo "${san_output}" | sed 's/^/    /'
    echo ""

    # Verify our EXTERNAL_HOST appears in the SAN
    if echo "${san_output}" | grep -q "${EXTERNAL_HOST}"; then
      log_ok "SAN includes '${EXTERNAL_HOST}' — hostname validation will pass."
    else
      log_warn "SAN does NOT include '${EXTERNAL_HOST}'."
      log_warn "A real Kafka client will reject the connection with a certificate hostname mismatch."
      log_warn "Check with whoever configured the listener before continuing if this is a production cluster."
      log_warn "Continuing for lab purposes..."
    fi
  else
    log_warn "Could not retrieve SAN from the certificate. Connectivity may still work."
  fi
}
