#!/usr/bin/env bash
# lib/ex7_produce_consume.sh — Exercise 7: Produce and consume a test message
# ─────────────────────────────────────────────────────────────────────────────
# Produces one timestamped message then consumes all messages from the beginning
# of the topic using --timeout-ms 15000.
#
# Verifies that the exact message produced in this session is found in the
# consumed output (a TimeoutException after the last message is expected and
# is NOT treated as an error here).
# ─────────────────────────────────────────────────────────────────────────────

run_ex7() {
  log_step "Exercise 7 — Produce and consume a message"

  cd "${WORKDIR}"

  local vol_flag=""
  if command -v getenforce &>/dev/null && [[ "$(getenforce 2>/dev/null)" = "Enforcing" ]]; then
    vol_flag=":Z"
  fi
  local docker_vol="${WORKDIR}:/mnt${vol_flag}"

  # ── 7a. Produce ─────────────────────────────────────────────────────────────
  local ts
  ts=$(date +%s)
  local message="hello-from-external-client-${ts}"
  log_info "Producing message: '${message}'"

  # A successful produce returns silently — no output is normal
  docker run --rm -i --network host \
    -v "${docker_vol}" \
    "confluentinc/cp-kafka:${CP_VERSION}" \
    bash -c "echo '${message}' | kafka-console-producer \
      --topic '${TOPIC}' \
      --bootstrap-server '${BOOTSTRAP}' \
      --command-config /mnt/client.properties" 2>&1 \
    | grep -v "^$" || true

  log_ok "Produce completed (silent success is expected — no output means no error)."

  # ── 7b. Consume ─────────────────────────────────────────────────────────────
  echo ""
  log_info "Consuming from topic '${TOPIC}' (--from-beginning, timeout 15 s)..."

  local consume_output
  # We capture stderr so the TimeoutException line doesn't pollute the display
  consume_output=$(docker run --rm --network host \
    -v "${docker_vol}" \
    "confluentinc/cp-kafka:${CP_VERSION}" \
    kafka-console-consumer \
      --topic "${TOPIC}" \
      --bootstrap-server "${BOOTSTRAP}" \
      --command-config /mnt/client.properties \
      --from-beginning \
      --timeout-ms 15000 2>&1 || true)

  # Filter out the expected TimeoutException line and "Processed a total of N"
  local clean_output
  clean_output=$(echo "${consume_output}" \
    | grep -v "TimeoutException" \
    | grep -v "Processed a total" \
    | grep -v "^$" || true)

  echo ""
  if [[ -n "${clean_output}" ]]; then
    log_ok "Messages received:"
    echo "${clean_output}" | sed 's/^/    /'
  else
    log_warn "No message content in consumer output."
    log_warn "Full consumer output:"
    echo "${consume_output}" | sed 's/^/    /'
  fi

  # ── 7c. Verify our message is in the output ────────────────────────────────
  echo ""
  if echo "${consume_output}" | grep -q "${message}"; then
    log_ok "Verification passed — produced message found in consumer output."
    log_ok "Message: '${message}'"
  else
    log_warn "The message produced in this session was not found in the consumer output."
    log_warn "Expected: '${message}'"
    log_warn "This may happen if the topic offset was already very large or the consumer timed out early."
    log_warn "Check the Messages tab in Control Center to confirm the record arrived."
  fi

  # Show the summary line from the consumer (expected Processed a total of N messages)
  local summary
  summary=$(echo "${consume_output}" | grep "Processed a total" || true)
  if [[ -n "${summary}" ]]; then
    log_info "${summary}"
  fi
}
