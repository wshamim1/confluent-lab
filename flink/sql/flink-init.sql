-- =============================================================================
-- flink-init.sql — Auto-loaded on every SQL client session
-- Copied into the container at /opt/flink/conf/flink-init.sql by run.sh
-- =============================================================================

SET 'sql-client.execution.result-mode' = 'tableau';

-- ---------------------------------------------------------------------------
-- sensor_readings — source table reading from local Kafka
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_readings (
    facility     STRING,
    machine_id   STRING,
    sensor_type  STRING,
    `timestamp`  STRING,
    unit         STRING,
    `value`      DOUBLE,
    proc_time    AS PROCTIME()
) WITH (
    'connector'                    = 'kafka',
    'topic'                        = 'sensor-readings',
    'properties.bootstrap.servers' = 'kafka:29092',
    'properties.group.id'          = 'flink-sql-reader',
    'scan.startup.mode'            = 'earliest-offset',
    'format'                       = 'json'
);

-- ---------------------------------------------------------------------------
-- sensor_aggregates — JDBC sink → PostgreSQL (INSERT INTO only)
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- equipment_alerts — JDBC sink → PostgreSQL (INSERT INTO only)
-- ---------------------------------------------------------------------------
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
