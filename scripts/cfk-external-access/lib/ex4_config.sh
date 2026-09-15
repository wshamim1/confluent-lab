#!/usr/bin/env bash
# lib/ex4_config.sh — Exercise 4: Build the Kafka client.properties file
# ─────────────────────────────────────────────────────────────────────────────
# Reads plain-users.json in $WORKDIR, picks the first user, and writes
# client.properties with:
#   - SASL_SSL security protocol
#   - SASL/PLAIN mechanism
#   - PEM truststore pointing at the CA cert (Kafka 2.7+ native PEM support)
#
# Output:
#   $WORKDIR/client.properties  (mode 644 — Docker non-root user must read it)
# ─────────────────────────────────────────────────────────────────────────────

run_ex4() {
  log_step "Exercise 4 — Build client.properties"

  cd "${WORKDIR}"

  log_info "Generating client.properties from credentials..."

  python3 - <<'PYEOF'
import json, sys, os

creds_path = "plain-users.json"
props_path = "client.properties"

try:
    with open(creds_path) as f:
        d = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"  ERROR: Could not read {creds_path}: {e}", file=sys.stderr)
    sys.exit(1)

if not d:
    print("  ERROR: plain-users.json contains no users.", file=sys.stderr)
    sys.exit(1)

user, pwd = next(iter(d.items()))

# ssl.truststore.location uses the container-internal /mnt mount path
# (the host path $WORKDIR/certs/ca.crt is mounted as /mnt/certs/ca.crt)
props = (
    "security.protocol=SASL_SSL\n"
    "sasl.mechanism=PLAIN\n"
    f'sasl.jaas.config=org.apache.kafka.common.security.plain.PlainLoginModule required username="{user}" password="{pwd}";\n'
    "ssl.truststore.type=PEM\n"
    "ssl.truststore.location=/mnt/certs/ca.crt\n"
)

with open(props_path, "w") as f:
    f.write(props)

print(f"  ✓  Config written for user: {user}")
print(f"  ✓  ssl.truststore.type=PEM  (no JKS needed — Kafka 2.7+ native PEM)")
PYEOF

  # chmod 644 — required so Docker's non-root user can read the file
  chmod 644 client.properties

  log_ok "client.properties written to ${WORKDIR}/client.properties"

  # Show the file with the password redacted so the student can verify the
  # structure without accidentally exposing credentials in terminal history
  echo ""
  log_info "client.properties (password redacted):"
  sed 's/password="[^"]*"/password="***REDACTED***"/' client.properties | sed 's/^/    /'
}
