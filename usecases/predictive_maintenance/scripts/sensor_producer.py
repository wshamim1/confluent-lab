"""
sensor_producer.py — Simulated IoT sensor readings for predictive maintenance.

Publishes JSON sensor readings to the ``sensor-readings`` Kafka topic.
Each message contains facility, machine_id, sensor_type, timestamp, unit, and value.

Usage
-----
    # Stream sensor readings continuously (default: 1 message/sec)
    KAFKA_ENV=cloud python3 scripts/producers/sensor_producer.py

    # Inject an anomaly spike immediately for a specific machine
    KAFKA_ENV=cloud python3 scripts/producers/sensor_producer.py \\
        --inject-anomaly --machine-id turbine-1 --sensor-type vibration

    # Custom rate (messages per second) and facility
    KAFKA_ENV=cloud python3 scripts/producers/sensor_producer.py \\
        --rate 2 --facility plant-b

    # Run for a fixed count then exit
    KAFKA_ENV=cloud python3 scripts/producers/sensor_producer.py --count 100
"""

import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, ".")
from auth import kafka_config

from confluent_kafka import Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import SerializationContext, MessageField

# ── Avro Schema (must match registered schema in Schema Registry) ─────────────
_SCHEMA_SENSOR_READINGS = """
{
  "type": "record",
  "name": "sensorreadings",
  "fields": [
    {"name": "machine_id",  "type": "string"},
    {"name": "sensor_type", "type": "string"},
    {"name": "value",       "type": "double"},
    {"name": "unit",        "type": "string"},
    {"name": "facility",    "type": "string"},
    {"name": "ts",          "type": "string"}
  ]
}
"""


def _sr_client() -> SchemaRegistryClient:
    """Return a SchemaRegistryClient for the active environment."""
    sr_url  = os.getenv("SCHEMA_REGISTRY_URL", "").rstrip("/")
    sr_user = os.getenv("CONTROL_CENTER_USERNAME", "admin")
    sr_pass = os.getenv("CONTROL_CENTER_PASSWORD", "")
    if not sr_url or not sr_pass:
        sys.exit("Missing SCHEMA_REGISTRY_URL or CONTROL_CENTER_PASSWORD in .env")
    return SchemaRegistryClient({
        "url":                  sr_url,
        "basic.auth.user.info": f"{sr_user}:{sr_pass}",
    })

# ── Machine catalogue ──────────────────────────────────────────────────────────

MACHINES = {
    "compressor-1": {
        "facility": "plant-a",
        "sensors": {
            "temperature": {"unit": "celsius",  "base": 85,  "noise": 3,  "anomaly_mult": 2.5},
            "pressure":    {"unit": "psi",       "base": 120, "noise": 5,  "anomaly_mult": 1.8},
            "vibration":   {"unit": "mm/s",      "base": 2.1, "noise": 0.3,"anomaly_mult": 6.0},
        },
    },
    "turbine-1": {
        "facility": "plant-a",
        "sensors": {
            "temperature": {"unit": "celsius",  "base": 210, "noise": 8,  "anomaly_mult": 2.0},
            "vibration":   {"unit": "mm/s",      "base": 1.8, "noise": 0.4,"anomaly_mult": 7.5},
            "rpm":         {"unit": "rpm",        "base": 3000,"noise": 50, "anomaly_mult": 1.3},
        },
    },
    "pump-1": {
        "facility": "plant-b",
        "sensors": {
            "pressure":    {"unit": "psi",       "base": 80,  "noise": 4,  "anomaly_mult": 2.2},
            "flow_rate":   {"unit": "L/min",      "base": 250, "noise": 10, "anomaly_mult": 0.4},
            "temperature": {"unit": "celsius",  "base": 65,  "noise": 2,  "anomaly_mult": 2.8},
        },
    },
    "hvac-1": {
        "facility": "plant-b",
        "sensors": {
            "temperature": {"unit": "celsius",  "base": 22,  "noise": 1,  "anomaly_mult": 2.0},
            "humidity":    {"unit": "percent",    "base": 45,  "noise": 3,  "anomaly_mult": 1.6},
            "pressure":    {"unit": "psi",       "base": 14.7,"noise": 0.2,"anomaly_mult": 1.9},
        },
    },
}

TOPIC_SENSOR = "sensor-readings"


# ── Value generation ───────────────────────────────────────────────────────────

def _normal_value(spec: dict, t: float) -> float:
    """Return a realistic sensor value with a slow sinusoidal drift + Gaussian noise."""
    drift = spec["base"] * 0.05 * math.sin(t / 120.0)   # slow 2-min cycle
    noise = random.gauss(0, spec["noise"])
    return round(spec["base"] + drift + noise, 3)


def _anomaly_value(spec: dict) -> float:
    """Return a clearly abnormal sensor value (above or below normal range)."""
    direction = random.choice([1, -1])
    magnitude = spec["base"] * (spec["anomaly_mult"] - 1)
    value = spec["base"] + direction * magnitude + random.gauss(0, spec["noise"])
    return round(abs(value), 3)


# ── Producer helpers ───────────────────────────────────────────────────────────

def _delivery_report(err, msg):
    if err:
        print(f"  ✗ delivery failed: {err}", file=sys.stderr)


def _make_record(
    machine_id: str,
    sensor_type: str,
    value: float,
    spec: dict,
    facility: str,
) -> dict:
    return {
        "machine_id":  machine_id,
        "sensor_type": sensor_type,
        "value":       float(value),
        "unit":        spec["unit"],
        "facility":    facility,
        "ts":          datetime.now(timezone.utc).isoformat(),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    cfg  = kafka_config(client_id="sensor-producer")
    cfg.pop("session.timeout.ms", None)   # consumer-only property, ignored by Producer
    prod = Producer(cfg)

    sr = _sr_client()
    serializer = AvroSerializer(sr, _SCHEMA_SENSOR_READINGS, lambda d, _: d)

    anomaly_targets: set[tuple[str, str]] = set()
    if args.inject_anomaly:
        anomaly_targets.add((args.machine_id, args.sensor_type))
        print(
            f"[sensor_producer] Anomaly injection ON  "
            f"→ machine={args.machine_id}  sensor={args.sensor_type}"
        )

    t0    = time.time()
    count = 0

    print(f"[sensor_producer] Publishing to topic '{TOPIC_SENSOR}' — Ctrl-C to stop")

    try:
        while True:
            t = time.time() - t0

            # Iterate all machines and their sensors each tick
            for machine_id, machine_def in MACHINES.items():
                # If --facility filter is set, skip others
                if args.facility and machine_def["facility"] != args.facility:
                    continue

                facility = machine_def["facility"]

                for sensor_type, spec in machine_def["sensors"].items():
                    if (machine_id, sensor_type) in anomaly_targets:
                        value = _anomaly_value(spec)
                        is_anomaly = True
                    else:
                        value = _normal_value(spec, t)
                        is_anomaly = False

                    record = _make_record(machine_id, sensor_type, value, spec, facility)
                    key    = f"{machine_id}:{sensor_type}"

                    avro_bytes = serializer(
                        record,
                        SerializationContext(TOPIC_SENSOR, MessageField.VALUE),
                    )

                    prod.produce(
                        TOPIC_SENSOR,
                        key=key.encode(),
                        value=avro_bytes,
                        callback=_delivery_report,
                    )

                    if args.verbose or is_anomaly:
                        flag = "⚠ ANOMALY" if is_anomaly else "·"
                        print(
                            f"  {flag}  {machine_id:<16} {sensor_type:<14} "
                            f"{value:>10.3f} {spec['unit']}"
                        )

                    count += 1
                    if args.count and count >= args.count:
                        prod.flush()
                        print(f"\n[sensor_producer] Done — sent {count} messages.")
                        return

            prod.poll(0)
            time.sleep(1.0 / max(args.rate, 0.1))

    except KeyboardInterrupt:
        print("\n[sensor_producer] Stopped by user.")
    finally:
        prod.flush()
        print(f"[sensor_producer] Total messages produced: {count}")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="IoT sensor reading producer")
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
