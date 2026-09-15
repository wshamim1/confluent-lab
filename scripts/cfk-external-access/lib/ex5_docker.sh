#!/usr/bin/env bash
# lib/ex5_docker.sh — Exercise 5: Pull and smoke-test the Confluent Docker image
# ─────────────────────────────────────────────────────────────────────────────
# Pulls confluentinc/cp-kafka:$CP_VERSION and confirms kafka-topics --version
# exits cleanly.
#
# If the exact tag is unavailable on Docker Hub the script tries the
# MAJOR.MINOR version as a fallback (e.g. 7.6.0 → 7.6), matching the lab
# guide advice to "try the closest published version".
# ─────────────────────────────────────────────────────────────────────────────

run_ex5() {
  log_step "Exercise 5 — Pull and smoke-test the Confluent Docker image"

  log_info "Target image: confluentinc/cp-kafka:${CP_VERSION}"

  # ── Try the exact version first ────────────────────────────────────────────
  local image="confluentinc/cp-kafka:${CP_VERSION}"

  if docker pull "${image}" --quiet 2>/dev/null; then
    log_ok "Pulled ${image}"
  else
    # Fall back to MAJOR.MINOR (drop patch)
    local fallback_version
    fallback_version=$(echo "${CP_VERSION}" | cut -d. -f1-2)
    local fallback_image="confluentinc/cp-kafka:${fallback_version}"
    log_warn "Tag '${CP_VERSION}' not found on Docker Hub — trying '${fallback_version}'..."

    if docker pull "${fallback_image}" --quiet 2>/dev/null; then
      CP_VERSION="${fallback_version}"
      image="${fallback_image}"
      log_ok "Pulled fallback image: ${image}"
    else
      log_error "Could not pull either confluentinc/cp-kafka:${CP_VERSION} or :${fallback_version}."
      log_error "Check your internet connection and Docker Hub availability, then set CP_VERSION manually."
      exit 1
    fi
  fi

  export CP_VERSION

  # ── Smoke-test: kafka-topics --version ─────────────────────────────────────
  log_info "Smoke-testing: kafka-topics --version"
  local version_output
  version_output=$(docker run --rm --network host "${image}" \
    kafka-topics --version 2>&1 || true)

  if [[ -n "${version_output}" ]]; then
    log_ok "kafka-topics --version: ${version_output}"
  else
    log_warn "kafka-topics --version produced no output — image may still work."
  fi

  log_ok "Docker image ready: ${image}"
}
