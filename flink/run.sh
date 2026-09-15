
#!/usr/bin/env bash
# =============================================================================
# run.sh — Manage the local Flink pipeline stack via Podman
#
# Usage:
#   ./flink/run.sh              # start everything (build on first run)
#   ./flink/run.sh start        # same as above
#   ./flink/run.sh stop         # stop and remove containers
#   ./flink/run.sh restart      # stop then start
#   ./flink/run.sh status       # show container status + key URLs
#   ./flink/run.sh sql          # open Flink SQL client (interactive)
#   ./flink/run.sh topic        # create the sensor-readings Kafka topic
#   ./flink/run.sh logs [svc]   # tail logs (default: all services)
#   ./flink/run.sh clean        # stop + remove containers AND volumes (wipes DB)
#
# Requirements:
#   podman 4.x+  (podman machine must be running: podman machine start)
#   podman compose (pip install podman-compose  OR  brew install podman-compose)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
PROJECT_NAME="flink-local"

# ── Helpers ───────────────────────────────────────────────────────────────────

_compose() {
    podman compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" "$@"
}

_check_podman() {
    if ! podman machine list 2>/dev/null | grep -q "Currently running"; then
        echo "⚠  Podman machine is not running. Starting it now..."
        podman machine start
    fi
}

_wait_healthy() {
    local container=$1
    local max=30
    local i=0
    echo -n "  Waiting for $container to be ready"
    while [ $i -lt $max ]; do
        if podman healthcheck run "$container" &>/dev/null; then
            echo " ✓"
            return 0
        fi
        echo -n "."
        sleep 2
        ((i++))
    done
    echo " (timeout — may still be starting)"
}

_print_urls() {
    echo ""
    echo "  ┌─────────────────────────────────────────────────────┐"
    echo "  │  Service          URL                               │"
    echo "  ├─────────────────────────────────────────────────────┤"
    echo "  │  Flink Web UI     http://localhost:8081             │"
    echo "  │  Flink SQL GW     http://localhost:8083             │"
    echo "  │  Kafka            localhost:9092                    │"
    echo "  │  PostgreSQL       localhost:5432  (flink/flink)     │"
    echo "  ├─────────────────────────────────────────────────────┤"
    echo "  │  FastAPI          uvicorn api.main:app --port 8000  │"
    echo "  │  Dashboard        streamlit run dashboard/app.py    │"
    echo "  └─────────────────────────────────────────────────────┘"
    echo ""
}

# ── Commands ──────────────────────────────────────────────────────────────────

cmd_start() {
    _check_podman
    echo "[run.sh] Building images (first run downloads ~200MB of JARs)..."
    _compose build
    echo "[run.sh] Starting stack..."
    _compose up -d
    echo ""
    echo "[run.sh] Waiting for services..."
    sleep 5
    _wait_healthy flink-kafka
    _wait_healthy flink-postgres
    # Copy init SQL into the jobmanager container so -i flag picks it up
    podman cp "$SCRIPT_DIR/sql/flink-init.sql" flink-jobmanager:/opt/flink/conf/flink-init.sql 2>/dev/null || true
    echo ""
    echo "[run.sh] Stack is up ✓"
    _print_urls
    echo "  Next steps:"
    echo "    1. Create topic:    ./flink/run.sh topic"
    echo "    2. Start producer:  python flink/producer/local_producer.py"
    echo "    3. Submit SQL job:  ./flink/scripts/submit_job.sh"
    echo "    4. Start API:       uvicorn flink.api.main:app --port 8000 (from repo root)"
    echo "    5. Dashboard:       streamlit run flink/dashboard/app.py"
}

cmd_stop() {
    echo "[run.sh] Stopping stack..."
    _compose down
    echo "[run.sh] Stopped ✓"
}

cmd_restart() {
    cmd_stop
    cmd_start
}

cmd_status() {
    echo "[run.sh] Container status:"
    _compose ps
    _print_urls
}

cmd_sql() {
    echo "[run.sh] Opening Flink SQL client (interactive)..."
    echo "  Tables are pre-loaded from flink/sql/flink-init.sql via the -i flag."
    echo "  Tip: run './flink/scripts/submit_job.sh' to submit the streaming jobs automatically."
    echo ""
    podman exec -it flink-jobmanager \
        /opt/flink/bin/sql-client.sh -i /opt/flink/conf/flink-init.sql
}

cmd_topic() {
    echo "[run.sh] Creating Kafka topic 'sensor-readings'..."
    podman exec flink-kafka \
        /opt/kafka/bin/kafka-topics.sh \
        --create --if-not-exists \
        --topic sensor-readings \
        --bootstrap-server localhost:9092 \
        --partitions 3 \
        --replication-factor 1
    echo "[run.sh] Topic created ✓"
    echo ""
    echo "[run.sh] All topics:"
    podman exec flink-kafka \
        /opt/kafka/bin/kafka-topics.sh \
        --list --bootstrap-server localhost:9092
}

cmd_logs() {
    local svc="${1:-}"
    if [ -n "$svc" ]; then
        _compose logs -f "$svc"
    else
        _compose logs -f
    fi
}

cmd_clean() {
    echo "[run.sh] Stopping stack and removing volumes (this wipes the PostgreSQL database)..."
    _compose down -v
    echo "[run.sh] Clean ✓"
}

# ── Entry point ───────────────────────────────────────────────────────────────

CMD="${1:-start}"

case "$CMD" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    status)  cmd_status ;;
    sql)     cmd_sql ;;
    topic)   cmd_topic ;;
    logs)    cmd_logs "${2:-}" ;;
    clean)   cmd_clean ;;
    *)
        echo "Unknown command: $CMD"
        echo "Usage: $0 {start|stop|restart|status|sql|topic|logs|clean}"
        exit 1
        ;;
esac
