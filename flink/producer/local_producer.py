"""
local_producer.py — Simulated IoT sensor readings for the local Flink pipeline.

Publishes JSON sensor readings to the ``sensor-readings`` Kafka topic on the
local Docker Kafka broker (localhost:9092).  No Confluent Cloud credentials
required — this is fully self-contained.

Mirrors the machine catalogue from the main confluent-lab sensor_producer.py
so that Flink SQL queries, dashboards, and alert thresholds are compatible.

Usage
-----
    # Install dependency (once)
    pip install kafka-python

    # Stream sensor readings continuously (default: 1 tick/sec)
    python producer/local_producer.py

    # Inject an anomaly for a specific machine+sensor
    python producer/local_producer.py --inject-anomaly --machine-id turbine-1 --sensor-type vibration

    # Higher rate, specific facility
    python producer/local_producer.py --rate 5 --facility plant-a

    # Fixed count then exit
    python producer/local_producer.py --count 200 --verbose
"""

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime, timezone

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="kafka")

from kafka import KafkaProducer

# ── Kafka config ──────────────────────────────────────────────────────────────
BOOTSTRAP_SERVERS = "localhost:9092"
TOPIC_SENSOR      = "sensor-readings"

# ── Machine catalogue ─────────────────────────────────────────────────────────
# Same machines/sensors as usecases/predictive_maintenance/scripts/sensor_producer.py
# so both pipelines share identical data shapes.

MACHINES = {
    "compressor-1": {
        "facility": "plant-a",
        "sensors": {
            "temperature": {"unit": "celsius", "base": 85,   "noise": 3,   "anomaly_mult": 2.5},
            "pressure":    {"unit": "psi",     "base": 120,  "noise": 5,   "anomaly_mult": 1.8},
            "vibration":   {"unit": "mm/s",    "base": 2.1,  "noise": 0.3, "anomaly_mult": 6.0},
        },
    },
    "turbine-1": {
        "facility": "plant-a",
        "sensors": {
            "temperature": {"unit": "celsius", "base": 210,  "noise": 8,   "anomaly_mult": 2.0},
            "vibration":   {"unit": "mm/s",    "base": 1.8,  "noise": 0.4, "anomaly_mult": 7.5},
            "rpm":         {"unit": "rpm",     "base": 3000, "noise": 50,  "anomaly_mult": 1.3},
        },
    },
    "pump-1": {
        "facility": "plant-b",
        "sensors": {
            "pressure":    {"unit": "psi",     "base": 80,   "noise": 4,   "anomaly_mult": 2.2},
            "flow_rate":   {"unit": "L/min",   "base": 250,  "noise": 10,  "anomaly_mult": 0.4},
            "temperature": {"unit": "celsius", "base": 65,   "noise": 2,   "anomaly_mult": 2.8},
        },
    },
    "hvac-1": {
        "facility": "plant-b",
        "sensors": {
            "temperature": {"unit": "celsius", "base": 22,   "noise": 1,   "anomaly_mult": 2.0},
            "humidity":    {"unit": "percent", "base": 45,   "noise": 3,   "anomaly_mult": 1.6},
            "pressure":    {"unit": "psi",     "base": 14.7, "noise": 0.2, "anomaly_mult": 1.9},
        },
    },
}


# ── Value generation ──────────────────────────────────────────────────────────

def _normal_value(spec: dict, t: float) -> float:
    """Realistic sensor value: slow sinusoidal drift + Gaussian noise."""
    drift = spec["base"] * 0.05 * math.sin(t / 120.0)
    noise = random.gauss(0, spec["noise"])
    return round(spec["base"] + drift + noise, 3)


def _anomaly_value(spec: dict) -> float:
    """Clearly abnormal value above or below the normal range."""
    direction = random.choice([1, -1])
    magnitude = spec["base"] * (spec["anomaly_mult"] - 1)
    return round(abs(spec["base"] + direction * magnitude + random.gauss(0, spec["noise"])), 3)


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    producer = KafkaProducer(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
    )

    anomaly_targets: set[tuple[str, str]] = set()
    if args.inject_anomaly:
        anomaly_targets.add((args.machine_id, args.sensor_type))
        print(
            f"[producer] Anomaly injection ON  "
            f"→ machine={args.machine_id}  sensor={args.sensor_type}"
        )

    t0    = time.time()
    count = 0

    print(f"[producer] Publishing to '{TOPIC_SENSOR}' on {BOOTSTRAP_SERVERS} — Ctrl-C to stop")

    try:
        while True:
            t = time.time() - t0

            for machine_id, machine_def in MACHINES.items():
                if args.facility and machine_def["facility"] != args.facility:
                    continue

                for sensor_type, spec in machine_def["sensors"].items():
                    is_anomaly = (machine_id, sensor_type) in anomaly_targets
                    value      = _anomaly_value(spec) if is_anomaly else _normal_value(spec, t)

                    record = {
                        "facility":    machine_def["facility"],
                        "machine_id":  machine_id,
                        "sensor_type": sensor_type,
                        "timestamp":   datetime.now(timezone.utc).isoformat(),
                        "unit":        spec["unit"],
                        "value":       value,
                    }

                    producer.send(
                        TOPIC_SENSOR,
                        key=f"{machine_id}:{sensor_type}",
                        value=record,
                    )

                    if args.verbose or is_anomaly:
                        flag = "⚠ ANOMALY" if is_anomaly else "·"
                        print(
                            f"  {flag}  {machine_id:<16} {sensor_type:<14} "
                            f"{value:>10.3f} {spec['unit']}"
                        )

                    count += 1
                    if args.count and count >= args.count:
                        producer.flush()
                        print(f"\n[producer] Done — sent {count} messages.")
                        return

            producer.flush()
            time.sleep(1.0 / max(args.rate, 0.1))

    except KeyboardInterrupt:
        print("\n[producer] Stopped by user.")
    finally:
        producer.flush()
        producer.close()
        print(f"[producer] Total messages produced: {count}")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Local IoT sensor producer for Flink pipeline")
    p.add_argument("--rate",           type=float, default=1.0,
                   help="Ticks per second (default: 1.0)")
    p.add_argument("--facility",       default="",
                   help="Filter to a single facility (plant-a | plant-b)")
    p.add_argument("--count",          type=int, default=0,
                   help="Stop after N messages (0 = run forever)")
    p.add_argument("--inject-anomaly", action="store_true",
                   help="Inject anomaly values for the specified machine+sensor")
    p.add_argument("--machine-id",     default="turbine-1",
                   help="Machine to inject anomaly on (default: turbine-1)")
    p.add_argument("--sensor-type",    default="vibration",
                   help="Sensor to inject anomaly on (default: vibration)")
    p.add_argument("--verbose",        action="store_true",
                   help="Print every message (default: only anomalies)")
    return p.parse_args()


if __name__ == "__main__":
    run(_parse())
