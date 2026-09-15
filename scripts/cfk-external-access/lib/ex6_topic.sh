#!/usr/bin/env bash
# lib/ex6_topic.sh — Exercise 6: Create a test topic through the external listener
# ─────────────────────────────────────────────────────────────────────────────
# Builds the bootstrap server list from EXTERNAL_HOST + PORT_OFFSET + NUM_BROKERS,
# creates the topic with partitions=NUM_BROKERS and replication-factor=NUM_BROKERS,
# then describes it and verifies that partition leaders are spread across brokers.
#
# Exports:
#   BOOTSTRAP  — comma-separated host:port list used in later exercises
# ─────────────────────────────────────────────────────────────────────────────

run_ex6() {
  log_step "Exercise 6 — Create a test topic through the external listener"

  cd "${WORKDIR}"

  # ── 6a. Build bootstrap server list ────────────────────────────────────────
  log_info "Building bootstrap server list..."
  BOOTSTRAP=""
  for i in $(seq 0 $((NUM_BROKERS - 1))); do
    local p=$((PORT_OFFSET + i))
    BOOTSTRAP="${BOOTSTRAP}${BOOTSTRAP:+,}${EXTERNAL_HOST}:${p}"
  done
  export BOOTSTRAP
  log_ok "Bootstrap servers: ${BOOTSTRAP}"
  log_ok "Topic            : ${TOPIC}"

  # ── 6b. Determine the Docker volume mount flag ──────────────────────────────
  # On SELinux-enforcing systems, :Z relabels the bind-mount for container access.
  # We detect this and add :Z automatically.
  local vol_flag=""
  if command -v getenforce &>/dev/null && [[ "$(getenforce 2>/dev/null)" = "Enforcing" ]]; then
    vol_flag=":Z"
    log_info "SELinux is Enforcing — adding :Z to Docker volume mount"
  fi

  local docker_vol="${WORKDIR}:/mnt${vol_flag}"

  # ── 6c. Create topic ────────────────────────────────────────────────────────
  echo ""
  log_info "Creating topic '${TOPIC}' (partitions=${NUM_BROKERS}, replication-factor=${NUM_BROKERS})..."

  local create_output
  create_output=$(docker run --rm --network host \
    -v "${docker_vol}" \
    "confluentinc/cp-kafka:${CP_VERSION}" \
    kafka-topics --create \
      --topic "${TOPIC}" \
      --partitions "${NUM_BROKERS}" \
      --replication-factor "${NUM_BROKERS}" \
      --bootstrap-server "${BOOTSTRAP}" \
      --command-config /mnt/client.properties 2>&1 || true)

  if echo "${create_output}" | grep -qi "already exists"; then
    log_warn "Topic '${TOPIC}' already exists — continuing (existing topic will be used)."
  elif echo "${create_output}" | grep -qi "Created topic"; then
    log_ok "Topic '${TOPIC}' created."
  elif echo "${create_output}" | grep -qi "error\|exception\|fail"; then
    log_error "Topic creation failed:"
    echo "${create_output}" | sed 's/^/    /'
    exit 1
  else
    # No explicit error but also no "Created" confirmation — show output and continue
    log_warn "Unexpected topic create output (may still be OK):"
    echo "${create_output}" | sed 's/^/    /'
  fi

  # ── 6d. Describe topic and verify leader spread ───────────────────────────
  echo ""
  log_info "Describing topic '${TOPIC}'..."

  local describe_output
  describe_output=$(docker run --rm --network host \
    -v "${docker_vol}" \
    "confluentinc/cp-kafka:${CP_VERSION}" \
    kafka-topics --describe \
      --topic "${TOPIC}" \
      --bootstrap-server "${BOOTSTRAP}" \
      --command-config /mnt/client.properties 2>&1 || true)

  echo "${describe_output}" | sed 's/^/    /'
  echo ""

  # Extract unique leader IDs
  local leader_count
  leader_count=$(echo "${describe_output}" \
    | grep -oP 'Leader:\s*\K\d+' \
    | sort -u \
    | wc -l || echo 0)

  if [[ "${leader_count}" -ge "${NUM_BROKERS}" ]]; then
    log_ok "Partition leaders spread across ${leader_count} broker(s) — healthy distribution."
  elif [[ "${leader_count}" -gt 1 ]]; then
    log_warn "Leaders spread across ${leader_count} of ${NUM_BROKERS} brokers — not fully balanced but functional."
  elif [[ "${leader_count}" -eq 1 ]]; then
    log_warn "All partitions have the same leader. Cluster may be single-broker or rebalancing."
  else
    log_warn "Could not parse leader distribution from describe output."
  fi
}
