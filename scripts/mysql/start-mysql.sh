#!/usr/bin/env bash
# start-mysql.sh
# ─────────────────────────────────────────────────────────────────────────────
# Start a MySQL 8 container in Podman, using the MySQL credentials from .env.
#
# Usage:
#   ./start-mysql.sh            # start (or reattach to existing) container
#   ./start-mysql.sh --stop     # stop and remove the container
#   ./start-mysql.sh --status   # show container status + connection details
#   ./start-mysql.sh --logs     # tail container logs
#
# Reads from .env:
#   MYSQL_HOST        (ignored for container start — always 127.0.0.1)
#   MYSQL_PORT        (host port mapped to container's 3306, default: 3306)
#   MYSQL_USER        (non-root user created on first start, default: kafkauser)
#   MYSQL_PASSWORD    (password for MYSQL_USER, default: kafkapass)
#   MYSQL_DATABASE    (database created on first start, default: kafkadb)
#   MYSQL_ROOT_PASSWORD (root password, default: rootpass)
#
# Requirements: podman (brew install podman)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Load .env ─────────────────────────────────────────────────────────────────
if [ -f .env ]; then
  set -a
  # Source only simple KEY=VALUE lines (no spaces in value, no comments)
  # shellcheck disable=SC1090
  source <(grep -v '^#' .env | grep -v '^$' | grep '^[A-Za-z_][A-Za-z0-9_]*=\S*$')
  set +a
fi

# ── Config (falls back to defaults if not in .env) ────────────────────────────
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:-kafkauser}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-kafkapass}"
MYSQL_DATABASE="${MYSQL_DATABASE:-kafkadb}"
MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-rootpass}"

CONTAINER_NAME="confluent-lab-mysql"
MYSQL_IMAGE="docker.io/library/mysql:8"

# ── Helpers ───────────────────────────────────────────────────────────────────
container_exists() {
  podman inspect "${CONTAINER_NAME}" &>/dev/null
}

container_running() {
  [ "$(podman inspect --format '{{.State.Status}}' "${CONTAINER_NAME}" 2>/dev/null)" = "running" ]
}

print_connection_details() {
  echo ""
  echo "  Connection details"
  echo "  ──────────────────────────────────────"
  echo "  Host     : 127.0.0.1"
  echo "  Port     : ${MYSQL_PORT}"
  echo "  Database : ${MYSQL_DATABASE}"
  echo "  User     : ${MYSQL_USER}"
  echo "  Password : ${MYSQL_PASSWORD}"
  echo "  Root pw  : ${MYSQL_ROOT_PASSWORD}"
  echo ""
  echo "  .env snippet (add if not already present):"
  echo "    MYSQL_HOST=127.0.0.1"
  echo "    MYSQL_PORT=${MYSQL_PORT}"
  echo "    MYSQL_USER=${MYSQL_USER}"
  echo "    MYSQL_PASSWORD=${MYSQL_PASSWORD}"
  echo "    MYSQL_DATABASE=${MYSQL_DATABASE}"
  echo "    MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}"
  echo ""
  echo "  CLI access:"
  echo "    podman exec -it ${CONTAINER_NAME} mysql -u${MYSQL_USER} -p${MYSQL_PASSWORD} ${MYSQL_DATABASE}"
  echo ""
  echo "  Send table to Kafka topic:"
  echo "    python3 mysql_to_kafka.py --table <tablename>"
  echo "    python3 mysql_to_kafka.py --table <tablename> --tail --watermark-col id"
  echo ""
}

# ── Argument handling ─────────────────────────────────────────────────────────
ACTION="${1:-start}"

case "${ACTION}" in
  --stop)
    if container_exists; then
      echo "==> Stopping and removing container '${CONTAINER_NAME}'..."
      podman stop "${CONTAINER_NAME}" 2>/dev/null || true
      podman rm   "${CONTAINER_NAME}" 2>/dev/null || true
      echo "  ✓ Container removed."
    else
      echo "  Container '${CONTAINER_NAME}' does not exist — nothing to stop."
    fi
    exit 0
    ;;

  --status)
    if container_exists; then
      STATUS=$(podman inspect --format '{{.State.Status}}' "${CONTAINER_NAME}")
      echo "  Container '${CONTAINER_NAME}' is: ${STATUS}"
      print_connection_details
    else
      echo "  Container '${CONTAINER_NAME}' does not exist."
      echo "  Run ./start-mysql.sh to create it."
    fi
    exit 0
    ;;

  --logs)
    if container_exists; then
      podman logs -f "${CONTAINER_NAME}"
    else
      echo "  Container '${CONTAINER_NAME}' does not exist."
    fi
    exit 0
    ;;

  start|"")
    : # handled below
    ;;

  *)
    echo "Usage: $0 [--stop | --status | --logs]"
    exit 1
    ;;
esac

# ── Check podman is available ─────────────────────────────────────────────────
if ! command -v podman &>/dev/null; then
  echo "✗ podman not found."
  echo "  Install it with:  brew install podman"
  echo "  Then initialise the VM:  podman machine init && podman machine start"
  exit 1
fi

# ── Reattach if already running ───────────────────────────────────────────────
if container_running; then
  echo "==> Container '${CONTAINER_NAME}' is already running — nothing to do."
  print_connection_details
  exit 0
fi

# ── Start stopped container (preserve existing data volume) ──────────────────
if container_exists; then
  echo "==> Container '${CONTAINER_NAME}' exists but is stopped — restarting..."
  podman start "${CONTAINER_NAME}"
  echo "  ✓ Restarted."
  print_connection_details
  exit 0
fi

# ── First run: pull image and create container ────────────────────────────────
echo "==> Pulling MySQL image (${MYSQL_IMAGE})..."
podman pull "${MYSQL_IMAGE}"

echo ""
echo "==> Creating container '${CONTAINER_NAME}'..."
podman run -d \
  --name "${CONTAINER_NAME}" \
  -e MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD}" \
  -e MYSQL_USER="${MYSQL_USER}" \
  -e MYSQL_PASSWORD="${MYSQL_PASSWORD}" \
  -e MYSQL_DATABASE="${MYSQL_DATABASE}" \
  -p "127.0.0.1:${MYSQL_PORT}:3306" \
  "${MYSQL_IMAGE}"

echo "  ✓ Container started."

# ── Wait for MySQL to be ready ────────────────────────────────────────────────
echo ""
echo "==> Waiting for MySQL to be ready (up to 90s)..."

MAX_WAIT=90
INTERVAL=3
ELAPSED=0
READY=0

# Phase 1: wait for root to be able to ping (mysqladmin ping uses root)
while [ "${ELAPSED}" -lt "${MAX_WAIT}" ]; do
  sleep "${INTERVAL}"
  ELAPSED=$((ELAPSED + INTERVAL))

  if podman exec "${CONTAINER_NAME}" \
       mysqladmin ping -uroot -p"${MYSQL_ROOT_PASSWORD}" --silent 2>/dev/null; then
    READY=1
    break
  fi

  echo "  Still waiting for root... (${ELAPSED}s)"
done

if [ "${READY}" -eq 0 ]; then
  echo "  ⚠ MySQL did not become ready in ${MAX_WAIT}s."
  echo "    Check logs: ./start-mysql.sh --logs"
  exit 1
fi

# Phase 2: wait for the non-root user to be provisioned.
# MySQL creates MYSQL_USER after root init completes — this can take a few
# extra seconds inside the container's entrypoint scripts.
echo "  Root is up. Waiting for user '${MYSQL_USER}' to be provisioned..."
READY=0
USER_WAIT=30
USER_ELAPSED=0

while [ "${USER_ELAPSED}" -lt "${USER_WAIT}" ]; do
  sleep "${INTERVAL}"
  USER_ELAPSED=$((USER_ELAPSED + INTERVAL))

  if podman exec "${CONTAINER_NAME}" \
       mysql -u"${MYSQL_USER}" -p"${MYSQL_PASSWORD}" \
       --connect-timeout=3 -e "SELECT 1;" "${MYSQL_DATABASE}" &>/dev/null; then
    READY=1
    break
  fi

  echo "  Still waiting for '${MYSQL_USER}'... (${USER_ELAPSED}s)"
done

if [ "${READY}" -eq 0 ]; then
  echo "  ⚠ User '${MYSQL_USER}' was not provisioned in time."
  echo "    Check logs: ./start-mysql.sh --logs"
  exit 1
fi

echo "  ✓ MySQL is ready (root + '${MYSQL_USER}' both accessible)."

# ── Seed a sample table for immediate use with mysql_to_kafka.py ──────────────
echo ""
echo "==> Creating sample table 'bookings' in database '${MYSQL_DATABASE}'..."

# Use root to create the table so kafkauser's SELECT privilege covers it too.
# MySQL's MYSQL_USER is granted ALL on MYSQL_DATABASE.* by the official image.
podman exec "${CONTAINER_NAME}" mysql \
  -uroot -p"${MYSQL_ROOT_PASSWORD}" "${MYSQL_DATABASE}" \
  -e "
CREATE TABLE IF NOT EXISTS bookings (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  customer_name VARCHAR(100) NOT NULL,
  destination   VARCHAR(100) NOT NULL,
  amount        DECIMAL(10,2) NOT NULL,
  status        VARCHAR(20)  NOT NULL DEFAULT 'NEW',
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO bookings (customer_name, destination, amount, status) VALUES
  ('Alice',   'New York',   299.99, 'NEW'),
  ('Bob',     'London',     499.50, 'NEW'),
  ('Charlie', 'Tokyo',      899.00, 'CONFIRMED'),
  ('Diana',   'Paris',      350.00, 'NEW'),
  ('Eve',     'Sydney',     750.25, 'CANCELLED');
"

echo "  ✓ Table 'bookings' created with 5 sample rows."

# ── Join flink-net if the Flink cluster is already running ────────────────────
# When install-flink-podman.sh has already created flink-net, attach this
# MySQL container to it so the Flink JDBC connector can reach it by name
# (confluent-lab-mysql:3306) instead of going via host.containers.internal.
FLINK_NETWORK="flink-net"
if podman network exists "${FLINK_NETWORK}" &>/dev/null; then
  ALREADY_ON=$(podman inspect "${CONTAINER_NAME}" \
    --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null \
    | tr ' ' '\n' | grep -c "^${FLINK_NETWORK}$" || true)
  if [ "${ALREADY_ON}" -eq 0 ]; then
    echo ""
    echo "==> Flink network '${FLINK_NETWORK}' detected — attaching MySQL container..."
    podman network connect "${FLINK_NETWORK}" "${CONTAINER_NAME}"
    echo "  ✓ MySQL is now reachable inside Flink as '${CONTAINER_NAME}:3306'"
  else
    echo "  ✓ MySQL is already on network '${FLINK_NETWORK}'"
  fi
else
  echo ""
  echo "  Note: Flink network '${FLINK_NETWORK}' not found."
  echo "  Start the Flink cluster first (./flink/install-flink-podman.sh), then"
  echo "  re-run this script or run:  podman network connect ${FLINK_NETWORK} ${CONTAINER_NAME}"
fi

print_connection_details
echo "==> Quick start:"
echo "    python3 mysql_to_kafka.py --table bookings --key-col id"
echo "    python3 mysql_to_kafka.py --table bookings --tail --watermark-col id --interval 5"
echo ""
