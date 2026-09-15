#!/usr/bin/env bash
# =============================================================================
# submit_job.sh — Create Flink SQL tables and submit the anomaly detection job
#
# Connects to the running flink-jobmanager container and executes the full
# pipeline setup: source table (Kafka) + sink tables (PostgreSQL) + INSERT jobs.
#
# Usage:
#   ./flink/scripts/submit_job.sh             # deploy everything
#   ./flink/scripts/submit_job.sh --dry-run   # print SQL only, don't execute
#   ./flink/scripts/submit_job.sh --status    # show running jobs
#   ./flink/scripts/submit_job.sh --teardown  # drop tables and stop jobs
# =============================================================================

set -euo pipefail

CONTAINER="flink-jobmanager"
SQL_CLIENT="podman exec -i $CONTAINER /opt/flink/bin/sql-client.sh"

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[submit_job]${NC} $*"; }
warn()    { echo -e "${YELLOW}[submit_job]${NC} $*"; }
die()     { echo -e "${RED}[submit_job] ERROR:${NC} $*" >&2; exit 1; }

# ── Check container is running ────────────────────────────────────────────────
_check_container() {
    if ! podman ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER}$"; then
        die "Container '$CONTAINER' is not running. Run: ./flink/run.sh start"
    fi
}

# ── SQL definitions ───────────────────────────────────────────────────────────

SQL_CREATE_SENSOR_READINGS="
CREATE TABLE IF NOT EXISTS sensor_readings (
    facility     STRING,
    machine_id   STRING,
    sensor_type  STRING,
    \`timestamp\` STRING,
    unit         STRING,
    \`value\`     DOUBLE,
    proc_time    AS PROCTIME()
) WITH (
    'connector'                    = 'kafka',
    'topic'                        = 'sensor-readings',
    'properties.bootstrap.servers' = 'kafka:29092',
    'properties.group.id'          = 'flink-sql-reader',
    'scan.startup.mode'            = 'earliest-offset',
    'format'                       = 'json'
);
"

SQL_CREATE_SENSOR_AGGREGATES="
CREATE TABLE IF NOT EXISTS sensor_aggregates (
    machine_id   STRING,
    sensor_type  STRING,
    facility     STRING,
    window_start TIMESTAMP(3),
    window_end   TIMESTAMP(3),
    avg_value    DOUBLE,
    min_value    DOUBLE,
    max_value    DOUBLE,
    event_count  BIGINT,
    unit         STRING
) WITH (
    'connector'  = 'jdbc',
    'url'        = 'jdbc:postgresql://postgres:5432/streaming',
    'table-name' = 'sensor_aggregates',
    'username'   = 'flink',
    'password'   = 'flink',
    'driver'     = 'org.postgresql.Driver'
);
"

SQL_CREATE_EQUIPMENT_ALERTS="
CREATE TABLE IF NOT EXISTS equipment_alerts (
    machine_id    STRING,
    sensor_type   STRING,
    facility      STRING,
    window_start  TIMESTAMP(3),
    window_end    TIMESTAMP(3),
    avg_value     DOUBLE,
    min_value     DOUBLE,
    max_value     DOUBLE,
    anomaly_score DOUBLE,
    severity      STRING,
    unit          STRING
) WITH (
    'connector'  = 'jdbc',
    'url'        = 'jdbc:postgresql://postgres:5432/streaming',
    'table-name' = 'equipment_alerts',
    'username'   = 'flink',
    'password'   = 'flink',
    'driver'     = 'org.postgresql.Driver'
);
"

SQL_INSERT_AGGREGATES="
INSERT INTO sensor_aggregates
SELECT
    machine_id,
    sensor_type,
    MAX(facility)                                AS facility,
    TUMBLE_START(proc_time, INTERVAL '1' MINUTE) AS window_start,
    TUMBLE_END  (proc_time, INTERVAL '1' MINUTE) AS window_end,
    AVG(\`value\`)                                AS avg_value,
    MIN(\`value\`)                                AS min_value,
    MAX(\`value\`)                                AS max_value,
    COUNT(*)                                     AS event_count,
    MAX(unit)                                    AS unit
FROM sensor_readings
GROUP BY
    machine_id,
    sensor_type,
    TUMBLE(proc_time, INTERVAL '1' MINUTE);
"

SQL_INSERT_ALERTS="
INSERT INTO equipment_alerts
SELECT
    machine_id,
    sensor_type,
    MAX(facility)                                AS facility,
    TUMBLE_START(proc_time, INTERVAL '1' MINUTE) AS window_start,
    TUMBLE_END  (proc_time, INTERVAL '1' MINUTE) AS window_end,
    AVG(\`value\`)                                AS avg_value,
    MIN(\`value\`)                                AS min_value,
    MAX(\`value\`)                                AS max_value,
    (MAX(\`value\`) - MIN(\`value\`)) / (AVG(\`value\`) + 0.0001) AS anomaly_score,
    CASE
        WHEN (MAX(\`value\`) - MIN(\`value\`)) / (AVG(\`value\`) + 0.0001) >= 2.0 THEN 'critical'
        WHEN (MAX(\`value\`) - MIN(\`value\`)) / (AVG(\`value\`) + 0.0001) >= 0.8 THEN 'warning'
        ELSE 'info'
    END AS severity,
    MAX(unit) AS unit
FROM sensor_readings
GROUP BY
    machine_id,
    sensor_type,
    TUMBLE(proc_time, INTERVAL '1' MINUTE)
HAVING
    (MAX(\`value\`) - MIN(\`value\`)) / (AVG(\`value\`) + 0.0001) >= 0.8;
"

SQL_DROP_TABLES="
DROP TABLE IF EXISTS sensor_readings;
DROP TABLE IF EXISTS sensor_aggregates;
DROP TABLE IF EXISTS equipment_alerts;
"

# ── Helpers ───────────────────────────────────────────────────────────────────

_run_sql() {
    local label="$1"
    local sql="$2"
    info "Executing: $label ..."
    echo "$sql" | $SQL_CLIENT --file /dev/stdin 2>&1 \
        | grep -v "^WARNING" \
        | grep -v "^$" \
        | grep -v "▒\|▓\|░\|Welcome\|HELP\|QUIT\|history" \
        || true
    info "$label ✓"
}

_run_sql_background() {
    local label="$1"
    local sql="$2"
    info "Submitting background job: $label ..."
    # INSERT jobs never return — run in background and capture job ID from output
    local output
    output=$(echo "$sql" | timeout 30 $SQL_CLIENT --file /dev/stdin 2>&1 \
        | grep -v "^WARNING" \
        | grep -E "Job ID|Submitting|job" \
        || true)
    echo "  $output"
    info "$label submitted ✓"
}

# ── Commands ──────────────────────────────────────────────────────────────────

cmd_deploy() {
    _check_container

    info "Creating tables and submitting Flink SQL jobs..."
    echo ""

    _run_sql "CREATE sensor_readings (Kafka source)"   "$SQL_CREATE_SENSOR_READINGS"
    _run_sql "CREATE sensor_aggregates (JDBC sink)"    "$SQL_CREATE_SENSOR_AGGREGATES"
    _run_sql "CREATE equipment_alerts (JDBC sink)"     "$SQL_CREATE_EQUIPMENT_ALERTS"

    echo ""
    info "Tables created. Submitting streaming jobs..."
    echo ""

    # Submit both INSERT jobs via the REST API (avoids blocking the SQL client)
    _submit_via_rest "aggregates-job" "$SQL_INSERT_AGGREGATES"
    _submit_via_rest "alerts-job"     "$SQL_INSERT_ALERTS"

    echo ""
    info "All done ✓"
    echo ""
    echo "  Check job status:   ./flink/scripts/submit_job.sh --status"
    echo "  Flink Web UI:       http://localhost:8081"
    echo "  Start producer:     python flink/producer/local_producer.py"
    echo "  Start API:          uvicorn flink.api.main:app --reload --port 8000"
}

_submit_via_rest() {
    local name="$1"
    local sql="$2"

    # Create a SQL Gateway session
    local session_resp
    session_resp=$(curl -sf -X POST http://localhost:8083/v1/sessions \
        -H 'Content-Type: application/json' \
        -d '{"properties": {"execution.runtime-mode": "streaming"}}' 2>/dev/null) || {
        warn "SQL Gateway not available — falling back to SQL client for $name"
        _run_sql_background "$name" "$sql"
        return
    }

    local session_handle
    session_handle=$(echo "$session_resp" | python3 -c "import sys,json; print(json.load(sys.stdin)['sessionHandle'])" 2>/dev/null) || {
        warn "Could not parse session handle — falling back to SQL client for $name"
        _run_sql_background "$name" "$sql"
        return
    }

    # First create the tables in this session
    local tables_sql="$SQL_CREATE_SENSOR_READINGS $SQL_CREATE_SENSOR_AGGREGATES $SQL_CREATE_EQUIPMENT_ALERTS"
    for stmt in "$SQL_CREATE_SENSOR_READINGS" "$SQL_CREATE_SENSOR_AGGREGATES" "$SQL_CREATE_EQUIPMENT_ALERTS"; do
        curl -sf -X POST "http://localhost:8083/v1/sessions/$session_handle/statements" \
            -H 'Content-Type: application/json' \
            -d "{\"statement\": $(echo "$stmt" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")}" \
            > /dev/null 2>&1 || true
        sleep 1
    done

    # Submit the INSERT job
    local result
    result=$(curl -sf -X POST "http://localhost:8083/v1/sessions/$session_handle/statements" \
        -H 'Content-Type: application/json' \
        -d "{\"statement\": $(echo "$sql" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")}" \
        2>/dev/null) || {
        warn "REST submission failed for $name — falling back to SQL client"
        _run_sql_background "$name" "$sql"
        return
    }

    local op_handle
    op_handle=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('operationHandle',''))" 2>/dev/null || echo "")
    info "$name submitted via SQL Gateway ✓  (operation: $op_handle)"
}

cmd_status() {
    _check_container
    info "Running Flink jobs:"
    podman exec "$CONTAINER" /opt/flink/bin/flink list -m localhost:8081 2>/dev/null \
        | grep -v "^WARNING" || true
    echo ""
    info "Flink Web UI: http://localhost:8081"
}

cmd_teardown() {
    _check_container
    warn "Stopping all running jobs..."
    # Cancel all running jobs
    local jobs
    jobs=$(podman exec "$CONTAINER" /opt/flink/bin/flink list -m localhost:8081 2>/dev/null \
        | grep -oE '[0-9a-f]{32}' || true)
    for job_id in $jobs; do
        info "Cancelling job $job_id ..."
        podman exec "$CONTAINER" /opt/flink/bin/flink cancel "$job_id" -m localhost:8081 2>/dev/null || true
    done
    info "Dropping tables..."
    _run_sql "DROP tables" "$SQL_DROP_TABLES"
    info "Teardown complete ✓"
}

cmd_dry_run() {
    echo ""
    echo "══════════════════════════════════════════════════════════════════"
    echo "  DRY RUN — SQL statements that would be submitted"
    echo "══════════════════════════════════════════════════════════════════"
    echo ""
    echo "── 1. sensor_readings (Kafka source) ──"
    echo "$SQL_CREATE_SENSOR_READINGS"
    echo "── 2. sensor_aggregates (JDBC sink) ──"
    echo "$SQL_CREATE_SENSOR_AGGREGATES"
    echo "── 3. equipment_alerts (JDBC sink) ──"
    echo "$SQL_CREATE_EQUIPMENT_ALERTS"
    echo "── 4. INSERT → sensor_aggregates (streaming job) ──"
    echo "$SQL_INSERT_AGGREGATES"
    echo "── 5. INSERT → equipment_alerts (streaming job) ──"
    echo "$SQL_INSERT_ALERTS"
}

# ── Entry point ───────────────────────────────────────────────────────────────

CMD="${1:-}"

case "$CMD" in
    ""| --deploy)   cmd_deploy ;;
    --dry-run)      cmd_dry_run ;;
    --status)       cmd_status ;;
    --teardown)     cmd_teardown ;;
    *)
        echo "Usage: $0 [--deploy | --dry-run | --status | --teardown]"
        exit 1
        ;;
esac
