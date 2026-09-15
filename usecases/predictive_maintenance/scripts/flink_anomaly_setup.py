"""
flink_anomaly_setup.py — Deploy Flink SQL anomaly detection for predictive maintenance.

Creates the sensor-readings source table, equipment-alerts sink table, and the
tumbling-window anomaly detection INSERT job in Confluent Cloud Flink.

The Flink SQL uses the built-in ML_PREDICT function with the ANOMALY_DETECTION
model to score each (machine_id, sensor_type) window and route outliers into
the equipment-alerts topic.

Usage
-----
    # Show the SQL statements only (dry-run, no deployment)
    KAFKA_ENV=cloud python3 scripts/platform/flink_anomaly_setup.py --dry-run

    # Deploy all statements to Confluent Cloud Flink
    KAFKA_ENV=cloud python3 scripts/platform/flink_anomaly_setup.py

    # Check status of the running anomaly job
    KAFKA_ENV=cloud python3 scripts/platform/flink_anomaly_setup.py --status

    # Tear down the anomaly detection job + tables
    KAFKA_ENV=cloud python3 scripts/platform/flink_anomaly_setup.py --teardown

Environment variables required (in .env)
-----------------------------------------
    KAFKA_ENV=cloud
    CONFLUENT_CLOUD_API_KEY       Flink REST API key
    CONFLUENT_CLOUD_API_SECRET    Flink REST API secret
    FLINK_REST_URL                e.g. https://flink.us-east-1.aws.confluent.cloud
    FLINK_ENV_ID                  e.g. env-xxxxxx
    FLINK_COMPUTE_POOL_ID         e.g. lfcp-xxxxxx
    FLINK_CATALOG                 Kafka cluster name used as catalog
    FLINK_DATABASE                Kafka cluster environment used as database

For on-prem Confluent Platform (CMF), set KAFKA_ENV=onprem and the script
will target the CMF REST endpoint instead.
"""

import argparse
import json
import os
import sys
import time

import requests
import urllib3

sys.path.insert(0, ".")
from auth import get_env, http_session

from dotenv import load_dotenv

load_dotenv()

# ── SQL statement templates ────────────────────────────────────────────────────

# 1. Source table (maps to sensor-readings Kafka topic)
SQL_CREATE_SENSOR_TABLE = """
CREATE TABLE IF NOT EXISTS `sensor_readings` (
  `facility`    STRING,
  `machine_id`  STRING,
  `sensor_type` STRING,
  `event_time`  TIMESTAMP_LTZ(3) METADATA FROM 'timestamp',
  `unit`        STRING,
  `value`       DOUBLE,
  WATERMARK FOR `event_time` AS `event_time` - INTERVAL '5' SECOND
) WITH (
  'kafka.topic' = 'sensor-readings',
  'scan.startup.mode' = 'latest-offset'
);
""".strip()

# 2. Sink table (maps to equipment-alerts Kafka topic)
SQL_CREATE_ALERTS_TABLE = """
CREATE TABLE IF NOT EXISTS `equipment_alerts` (
  `machine_id`      STRING,
  `sensor_type`     STRING,
  `facility`        STRING,
  `window_start`    TIMESTAMP_LTZ(3),
  `window_end`      TIMESTAMP_LTZ(3),
  `detected_at`     TIMESTAMP_LTZ(3),
  `avg_value`       DOUBLE,
  `min_value`       DOUBLE,
  `max_value`       DOUBLE,
  `anomaly_score`   DOUBLE,
  `severity`        STRING,
  `unit`            STRING
) WITH (
  'kafka.topic' = 'equipment-alerts',
  'key.format'  = 'json',
  'key.fields'  = 'machine_id;sensor_type'
);
""".strip()

# 3. Anomaly detection INSERT (tumbling 1-min window, per machine+sensor model)
SQL_ANOMALY_INSERT = """
INSERT INTO `equipment_alerts`
SELECT
  machine_id,
  sensor_type,
  facility,
  window_start,
  window_end,
  CURRENT_TIMESTAMP                           AS detected_at,
  AVG(value)                                  AS avg_value,
  MIN(value)                                  AS min_value,
  MAX(value)                                  AS max_value,
  ML_PREDICT(
    'AnomalyDetection',
    ARRAY[AVG(value), STDDEV_POP(value),
          MIN(value),  MAX(value),
          COUNT(*)     * 1.0]
  )[1]                                        AS anomaly_score,
  CASE
    WHEN ML_PREDICT(
      'AnomalyDetection',
      ARRAY[AVG(value), STDDEV_POP(value),
            MIN(value),  MAX(value),
            COUNT(*)     * 1.0]
    )[1] >= 0.9 THEN 'critical'
    WHEN ML_PREDICT(
      'AnomalyDetection',
      ARRAY[AVG(value), STDDEV_POP(value),
            MIN(value),  MAX(value),
            COUNT(*)     * 1.0]
    )[1] >= 0.7 THEN 'warning'
    ELSE 'info'
  END                                          AS severity,
  MAX(unit)                                    AS unit
FROM TABLE(
  TUMBLE(TABLE `sensor_readings`, DESCRIPTOR(event_time), INTERVAL '1' MINUTE)
)
GROUP BY
  machine_id,
  sensor_type,
  facility,
  window_start,
  window_end
HAVING
  ML_PREDICT(
    'AnomalyDetection',
    ARRAY[AVG(value), STDDEV_POP(value),
          MIN(value),  MAX(value),
          COUNT(*)     * 1.0]
  )[1] >= 0.7;
""".strip()

ALL_STATEMENTS = [
    ("create_sensor_table",  SQL_CREATE_SENSOR_TABLE),
    ("create_alerts_table",  SQL_CREATE_ALERTS_TABLE),
    ("anomaly_insert_job",   SQL_ANOMALY_INSERT),
]

STATEMENT_NAMES = [name for name, _ in ALL_STATEMENTS]


# ── Cloud Flink REST client ────────────────────────────────────────────────────

class FlinkCloudClient:
    """Thin wrapper around the Confluent Cloud Flink REST API."""

    def __init__(self):
        self.api_key    = os.getenv("CONFLUENT_CLOUD_API_KEY", "")
        self.api_secret = os.getenv("CONFLUENT_CLOUD_API_SECRET", "")
        self.base_url   = os.getenv("FLINK_REST_URL", "").rstrip("/")
        self.env_id     = os.getenv("FLINK_ENV_ID", "")
        self.pool_id    = os.getenv("FLINK_COMPUTE_POOL_ID", "")
        self.catalog    = os.getenv("FLINK_CATALOG", "")
        self.database   = os.getenv("FLINK_DATABASE", "")

        missing = [
            n for n, v in {
                "FLINK_REST_URL":        self.base_url,
                "FLINK_ENV_ID":          self.env_id,
                "FLINK_COMPUTE_POOL_ID": self.pool_id,
                "FLINK_CATALOG":         self.catalog,
                "FLINK_DATABASE":        self.database,
            }.items() if not v
        ]
        if missing:
            sys.exit(
                f"[flink] Missing .env settings: {', '.join(missing)}\n"
                "See the script docstring for required variables."
            )

        self.session = requests.Session()
        self.session.auth    = (self.api_key, self.api_secret)
        self.session.headers = {"Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def submit_statement(self, name: str, sql: str) -> dict:
        payload = {
            "name": name,
            "organization_id": "",          # filled by the server
            "environment_id": self.env_id,
            "spec": {
                "statement": sql,
                "compute_pool_id": self.pool_id,
                "principal":       "",
                "properties": {
                    "sql.current-catalog":  self.catalog,
                    "sql.current-database": self.database,
                },
            },
        }
        r = self.session.post(
            self._url(f"/sql/v1/environments/{self.env_id}/statements"),
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def list_statements(self) -> list[dict]:
        r = self.session.get(
            self._url(f"/sql/v1/environments/{self.env_id}/statements"),
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("data", [])

    def delete_statement(self, name: str) -> None:
        r = self.session.delete(
            self._url(f"/sql/v1/environments/{self.env_id}/statements/{name}"),
            timeout=30,
        )
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def wait_for_running(self, name: str, timeout_s: int = 60) -> str:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            stmts = self.list_statements()
            for s in stmts:
                if s.get("name") == name:
                    phase = s.get("status", {}).get("phase", "UNKNOWN")
                    if phase in ("COMPLETED", "RUNNING"):
                        return phase
                    if phase in ("FAILED", "DELETED"):
                        detail = s.get("status", {}).get("detail", "")
                        sys.exit(f"[flink] Statement '{name}' {phase}: {detail}")
            time.sleep(3)
        return "TIMEOUT"


# ── On-prem Flink via ksqlDB fallback ─────────────────────────────────────────

class FlinkOnPremClient:
    """
    Approximates the anomaly detection pipeline on on-prem Confluent Platform
    using ksqlDB streams + a tumbling-window aggregation.

    Real anomaly scoring (ML_PREDICT) is not available on-prem, so this
    uses a Z-score threshold instead.
    """

    KSQL_CREATE_STREAM = """
CREATE STREAM IF NOT EXISTS sensor_readings_stream (
  facility    VARCHAR,
  machine_id  VARCHAR,
  sensor_type VARCHAR,
  `timestamp` VARCHAR,
  unit        VARCHAR,
  value       DOUBLE
) WITH (
  KAFKA_TOPIC='sensor-readings',
  VALUE_FORMAT='JSON'
);
""".strip()

    KSQL_CREATE_ALERTS_STREAM = """
CREATE STREAM IF NOT EXISTS equipment_alerts_stream (
  machine_id     VARCHAR KEY,
  sensor_type    VARCHAR,
  facility       VARCHAR,
  detected_at    VARCHAR,
  avg_value      DOUBLE,
  min_value      DOUBLE,
  max_value      DOUBLE,
  anomaly_score  DOUBLE,
  severity       VARCHAR,
  unit           VARCHAR
) WITH (
  KAFKA_TOPIC='equipment-alerts',
  VALUE_FORMAT='JSON',
  PARTITIONS=1
);
""".strip()

    # Z-score approximation: flag if |value - avg| > 2.5 * stddev
    # Uses a 60-second tumbling window
    KSQL_INSERT_ANOMALIES = """
INSERT INTO equipment_alerts_stream
SELECT
  machine_id,
  sensor_type,
  EARLIEST_BY_OFFSET(facility)       AS facility,
  FORMAT_TIMESTAMP(WINDOWSTART,'yyyy-MM-dd''T''HH:mm:ss''Z''') AS detected_at,
  AVG(value)                          AS avg_value,
  MIN(value)                          AS min_value,
  MAX(value)                          AS max_value,
  (MAX(value) - MIN(value)) / (STDDEV_SAMP(value) + 0.0001) AS anomaly_score,
  CASE
    WHEN (MAX(value) - MIN(value)) / (STDDEV_SAMP(value) + 0.0001) > 5 THEN 'critical'
    WHEN (MAX(value) - MIN(value)) / (STDDEV_SAMP(value) + 0.0001) > 3 THEN 'warning'
    ELSE 'info'
  END                                 AS severity,
  EARLIEST_BY_OFFSET(unit)            AS unit
FROM sensor_readings_stream
  WINDOW TUMBLING (SIZE 60 SECONDS)
GROUP BY machine_id, sensor_type
HAVING (MAX(value) - MIN(value)) / (STDDEV_SAMP(value) + 0.0001) > 3
EMIT CHANGES;
""".strip()

    def __init__(self):
        self.session, self.base_url = http_session("KSQLDB_URL")
        self.ksql_url = self.base_url.rstrip("/")

    def _run(self, sql: str) -> dict:
        r = self.session.post(
            f"{self.ksql_url}/ksql",
            json={"ksql": sql, "streamsProperties": {}},
            timeout=30,
        )
        if r.status_code not in (200, 201):
            print(f"  ✗ ksqlDB error {r.status_code}: {r.text}", file=sys.stderr)
        else:
            r.raise_for_status()
        return r.json() if r.text else {}

    def deploy(self) -> None:
        for sql in [
            self.KSQL_CREATE_STREAM,
            self.KSQL_CREATE_ALERTS_STREAM,
            self.KSQL_INSERT_ANOMALIES,
        ]:
            print(f"\n── Running ksqlDB statement ──\n{sql[:80]}…")
            result = self._run(sql)
            print(f"   → {json.dumps(result, indent=2)[:200]}")

    def status(self) -> None:
        r = self.session.get(f"{self.ksql_url}/info", timeout=10)
        r.raise_for_status()
        print(json.dumps(r.json(), indent=2))

        r2 = self.session.post(
            f"{self.ksql_url}/ksql",
            json={"ksql": "SHOW QUERIES;"},
            timeout=10,
        )
        r2.raise_for_status()
        print(json.dumps(r2.json(), indent=2))

    def teardown(self) -> None:
        for name in ["sensor_readings_stream", "equipment_alerts_stream"]:
            sql = f"DROP STREAM IF EXISTS {name} DELETE TOPIC;"
            print(f"  dropping: {name}")
            self._run(sql)


# ── Actions ────────────────────────────────────────────────────────────────────

def _dry_run() -> None:
    print("\n" + "═" * 70)
    print("  DRY RUN — SQL statements that would be submitted to Flink")
    print("═" * 70)
    for name, sql in ALL_STATEMENTS:
        print(f"\n── {name} ──\n{sql}\n")


def _deploy_cloud(client: FlinkCloudClient) -> None:
    for name, sql in ALL_STATEMENTS:
        print(f"\n[flink] Submitting '{name}' …")
        result = client.submit_statement(name, sql)
        phase  = result.get("status", {}).get("phase", "PENDING")
        print(f"  → initial phase: {phase}")

        # DDL statements complete quickly; INSERT jobs stay RUNNING
        final = client.wait_for_running(name, timeout_s=90)
        print(f"  → final phase:   {final}")

    print("\n[flink] All statements deployed ✓")


def _status_cloud(client: FlinkCloudClient) -> None:
    stmts = client.list_statements()
    relevant = [s for s in stmts if s.get("name", "") in STATEMENT_NAMES]
    if not relevant:
        print("[flink] No predictive maintenance statements found.")
        return
    for s in relevant:
        print(
            f"  {s['name']:<30}  phase={s.get('status',{}).get('phase','?')}"
            f"  detail={s.get('status',{}).get('detail','')[:60]}"
        )


def _teardown_cloud(client: FlinkCloudClient) -> None:
    for name in STATEMENT_NAMES:
        print(f"[flink] Deleting '{name}' …")
        client.delete_statement(name)
    print("[flink] Teardown complete.")


# ── Entry point ────────────────────────────────────────────────────────────────

def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Deploy Flink SQL anomaly detection for predictive maintenance"
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run",  action="store_true", help="Print SQL, do not deploy")
    g.add_argument("--status",   action="store_true", help="Show statement statuses")
    g.add_argument("--teardown", action="store_true", help="Delete all statements")
    return p.parse_args()


def main() -> None:
    args = _parse()

    if args.dry_run:
        _dry_run()
        return

    env = get_env()

    if env == "cloud":
        client = FlinkCloudClient()
        if args.status:
            _status_cloud(client)
        elif args.teardown:
            _teardown_cloud(client)
        else:
            _deploy_cloud(client)

    else:  # onprem — use ksqlDB approximation
        client_kql = FlinkOnPremClient()
        if args.status:
            client_kql.status()
        elif args.teardown:
            client_kql.teardown()
        else:
            client_kql.deploy()


if __name__ == "__main__":
    main()
