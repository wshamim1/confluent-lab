-- =============================================================================
-- init.sql — PostgreSQL schema for the local Flink pipeline sink
-- Auto-executed by Docker on first container start (mounted as
-- /docker-entrypoint-initdb.d/init.sql).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- sensor_aggregates
-- Written by the Flink SQL tumbling-window job (jobs/anomaly_sql.sql).
-- One row per (machine_id, sensor_type, 1-minute window).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_aggregates (
    machine_id      TEXT,
    sensor_type     TEXT,
    facility        TEXT,
    window_start    TIMESTAMP,
    window_end      TIMESTAMP,
    avg_value       DOUBLE PRECISION,
    min_value       DOUBLE PRECISION,
    max_value       DOUBLE PRECISION,
    event_count     INTEGER,
    unit            TEXT,
    inserted_at     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sa_machine_window
    ON sensor_aggregates (machine_id, window_start DESC);

-- ---------------------------------------------------------------------------
-- equipment_alerts
-- Written by Flink when the anomaly score threshold is crossed.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS equipment_alerts (
    machine_id      TEXT,
    sensor_type     TEXT,
    facility        TEXT,
    window_start    TIMESTAMP,
    window_end      TIMESTAMP,
    avg_value       DOUBLE PRECISION,
    min_value       DOUBLE PRECISION,
    max_value       DOUBLE PRECISION,
    anomaly_score   DOUBLE PRECISION,
    severity        TEXT,
    unit            TEXT,
    detected_at     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ea_machine_detected
    ON equipment_alerts (machine_id, detected_at DESC);
