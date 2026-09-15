"""
sensor_job.py — PyFlink DataStream API job for the local Flink pipeline.

Alternative to anomaly_sql.sql — uses the Python DataStream API instead of
Flink SQL.  Produces the same output: rolling 1-minute window aggregates
written to PostgreSQL sensor_aggregates, and anomaly alerts to equipment_alerts.

Pipeline
--------
    Kafka sensor-readings
        │
        ▼ KafkaSource (JSON deserialisation)
        │
        ▼ map → SensorEvent dataclass
        │
        ▼ key_by(machine_id, sensor_type)
        │
        ▼ TumblingProcessingTimeWindows(60s)
        │
        ▼ aggregate (avg / min / max / count)
        │
        ├─► JdbcSink → sensor_aggregates  (all windows)
        └─► filter anomaly_score >= 0.8
              └─► JdbcSink → equipment_alerts

Submission
----------
    # From the repo root, with Flink cluster running via docker-compose:
    docker exec -it flink-jobmanager \
        /opt/flink/bin/flink run \
        --python /opt/flink/userjobs/sensor_job.py \
        -pyfs /opt/flink/userjobs

    # Or using the local flink binary if installed:
    flink run -py flink/jobs/sensor_job.py -m localhost:8081

Requirements
------------
    pip install apache-flink==1.20.0
"""

import json
from dataclasses import dataclass
from typing import Iterable, Tuple

from pyflink.common import Types, WatermarkStrategy
from pyflink.common.serialization import SimpleStringSchema
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.jdbc import JdbcConnectionOptions, JdbcSink
from pyflink.datastream.connectors.kafka import KafkaSource, KafkaOffsetResetStrategy
from pyflink.datastream.window import TumblingProcessingTimeWindows
from pyflink.common.time import Time


# ── Config ────────────────────────────────────────────────────────────────────

KAFKA_BOOTSTRAP  = "kafka:29092"          # internal Docker network
TOPIC_SENSORS    = "sensor-readings"
CONSUMER_GROUP   = "pyflink-job"
POSTGRES_URL     = "jdbc:postgresql://postgres:5432/streaming"
POSTGRES_USER    = "flink"
POSTGRES_PASS    = "flink"
POSTGRES_DRIVER  = "org.postgresql.Driver"
WINDOW_SECONDS   = 60
ANOMALY_THRESH   = 0.8                    # anomaly_score = (max-min)/(avg+ε)


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class SensorEvent:
    facility:    str
    machine_id:  str
    sensor_type: str
    unit:        str
    value:       float


@dataclass
class WindowResult:
    machine_id:   str
    sensor_type:  str
    facility:     str
    window_start: str    # ISO string — Flink proc-time windows don't carry timestamps natively
    window_end:   str
    avg_value:    float
    min_value:    float
    max_value:    float
    event_count:  int
    unit:         str
    anomaly_score: float
    severity:     str


# ── Aggregation logic ─────────────────────────────────────────────────────────

class SensorAggregateFunction:
    """Accumulates sum/min/max/count for a (machine_id, sensor_type) window."""

    def create_accumulator(self):
        return {"sum": 0.0, "min": float("inf"), "max": float("-inf"), "count": 0,
                "facility": "", "unit": ""}

    def add(self, value: SensorEvent, acc):
        acc["sum"]   += value.value
        acc["min"]    = min(acc["min"], value.value)
        acc["max"]    = max(acc["max"], value.value)
        acc["count"] += 1
        acc["facility"] = value.facility
        acc["unit"]     = value.unit
        return acc

    def get_result(self, acc):
        avg   = acc["sum"] / acc["count"] if acc["count"] else 0.0
        score = (acc["max"] - acc["min"]) / (avg + 0.0001)
        sev   = ("critical" if score >= 2.0 else
                 "warning"  if score >= ANOMALY_THRESH else "info")
        return (avg, acc["min"], acc["max"], acc["count"],
                acc["facility"], acc["unit"], score, sev)

    def merge(self, acc_a, acc_b):
        return {
            "sum":      acc_a["sum"]   + acc_b["sum"],
            "min":      min(acc_a["min"], acc_b["min"]),
            "max":      max(acc_a["max"], acc_b["max"]),
            "count":    acc_a["count"] + acc_b["count"],
            "facility": acc_a["facility"] or acc_b["facility"],
            "unit":     acc_a["unit"]     or acc_b["unit"],
        }


# ── JDBC sink helpers ─────────────────────────────────────────────────────────

_JDBC_OPTS = (
    JdbcConnectionOptions.JdbcConnectionOptionsBuilder()
    .with_url(POSTGRES_URL)
    .with_driver_name(POSTGRES_DRIVER)
    .with_user_name(POSTGRES_USER)
    .with_password(POSTGRES_PASS)
    .build()
)

_INSERT_AGGREGATES = """
    INSERT INTO sensor_aggregates
        (machine_id, sensor_type, facility, window_start, window_end,
         avg_value, min_value, max_value, event_count, unit)
    VALUES (?, ?, ?, ?::timestamp, ?::timestamp, ?, ?, ?, ?, ?)
""".strip()

_INSERT_ALERTS = """
    INSERT INTO equipment_alerts
        (machine_id, sensor_type, facility, window_start, window_end,
         avg_value, min_value, max_value, anomaly_score, severity, unit)
    VALUES (?, ?, ?, ?::timestamp, ?::timestamp, ?, ?, ?, ?, ?, ?)
""".strip()

_AGGREGATE_TYPE = Types.ROW([
    Types.STRING(), Types.STRING(), Types.STRING(),
    Types.STRING(), Types.STRING(),
    Types.DOUBLE(), Types.DOUBLE(), Types.DOUBLE(), Types.INT(), Types.STRING(),
])

_ALERT_TYPE = Types.ROW([
    Types.STRING(), Types.STRING(), Types.STRING(),
    Types.STRING(), Types.STRING(),
    Types.DOUBLE(), Types.DOUBLE(), Types.DOUBLE(),
    Types.DOUBLE(), Types.STRING(), Types.STRING(),
])


# ── Job ───────────────────────────────────────────────────────────────────────

def main():
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(1)

    # ── Source ────────────────────────────────────────────────────────────────
    source = (
        KafkaSource.builder()
        .set_bootstrap_servers(KAFKA_BOOTSTRAP)
        .set_topics(TOPIC_SENSORS)
        .set_group_id(CONSUMER_GROUP)
        .set_starting_offsets(KafkaOffsetResetStrategy.EARLIEST)
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )

    raw_stream = env.from_source(
        source,
        WatermarkStrategy.no_watermarks(),
        "Kafka: sensor-readings",
    )

    # ── Parse JSON → SensorEvent ──────────────────────────────────────────────
    def parse(msg: str):
        try:
            d = json.loads(msg)
            return SensorEvent(
                facility=d.get("facility", ""),
                machine_id=d["machine_id"],
                sensor_type=d["sensor_type"],
                unit=d.get("unit", ""),
                value=float(d["value"]),
            )
        except Exception:
            return None

    sensor_stream = (
        raw_stream
        .map(parse)
        .filter(lambda x: x is not None)
    )

    # ── Key by machine+sensor, apply tumbling window ──────────────────────────
    windowed = (
        sensor_stream
        .key_by(lambda e: f"{e.machine_id}:{e.sensor_type}")
        .window(TumblingProcessingTimeWindows.of(Time.seconds(WINDOW_SECONDS)))
        .aggregate(SensorAggregateFunction())
    )

    # windowed emits tuples: (machine_id, sensor_type, avg, min, max, count, facility, unit, score, sev)
    # We need to carry the key through — use a process window function to get the window bounds.
    # For simplicity with proc-time, we compute window_start/end from the element's processing time.

    from pyflink.datastream import ProcessWindowFunction
    from pyflink.datastream.window import TimeWindow
    import datetime as dt

    class EnrichWithWindow(ProcessWindowFunction):
        def process(self, key: str, context, elements: Iterable) -> Iterable:
            win: TimeWindow = context.window()
            ws = dt.datetime.fromtimestamp(win.start / 1000, tz=dt.timezone.utc).isoformat()
            we = dt.datetime.fromtimestamp(win.end   / 1000, tz=dt.timezone.utc).isoformat()
            machine_id, sensor_type = key.split(":", 1)

            for (avg, mn, mx, cnt, facility, unit, score, sev) in elements:
                yield (machine_id, sensor_type, facility, ws, we,
                       avg, mn, mx, cnt, unit, score, sev)

    # Re-run using process window function to get window bounds
    enriched = (
        sensor_stream
        .key_by(lambda e: f"{e.machine_id}:{e.sensor_type}")
        .window(TumblingProcessingTimeWindows.of(Time.seconds(WINDOW_SECONDS)))
        .process(EnrichWithWindow())
    )

    # ── Sink 1: all aggregates → PostgreSQL ───────────────────────────────────
    agg_rows = enriched.map(
        lambda r: (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9]),
        output_type=_AGGREGATE_TYPE,
    )
    agg_rows.add_sink(
        JdbcSink.sink(_INSERT_AGGREGATES, _AGGREGATE_TYPE, _JDBC_OPTS)
    )

    # ── Sink 2: anomaly alerts only → PostgreSQL ──────────────────────────────
    alert_rows = (
        enriched
        .filter(lambda r: r[10] >= ANOMALY_THRESH)
        .map(
            lambda r: (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[10], r[11], r[9]),
            output_type=_ALERT_TYPE,
        )
    )
    alert_rows.add_sink(
        JdbcSink.sink(_INSERT_ALERTS, _ALERT_TYPE, _JDBC_OPTS)
    )

    env.execute("Sensor Analytics — Local Flink Pipeline")


if __name__ == "__main__":
    main()
