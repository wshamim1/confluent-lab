"""
scripts/platform/register_all_schemas.py — Register Avro schemas for all lab topics.

Flink's KafkaCatalog only surfaces topics that have a schema registered in
Schema Registry under <topic>-value.  Run this once after the topics are created.

Usage:
    KAFKA_ENV=onprem python3 scripts/platform/register_all_schemas.py
    KAFKA_ENV=onprem python3 scripts/platform/register_all_schemas.py --topic retail-orders
    KAFKA_ENV=onprem python3 scripts/platform/register_all_schemas.py --list
"""

import argparse
import json
import sys

sys.path.insert(0, ".")
from auth import http_session

# ── Schema catalogue ───────────────────────────────────────────────────────────

# Flink's KafkaCatalog requires: namespace + PascalCase record name.
# These match the original v1 schemas that Flink successfully resolved.
SCHEMAS = {
    # ── Retail ────────────────────────────────────────────────────────────────
    "retail-orders": {
        "type": "record", "name": "RetailOrder", "namespace": "com.lab.retail",
        "fields": [
            {"name": "event_id",      "type": "string"},
            {"name": "event_type",    "type": "string"},
            {"name": "customer_id",   "type": "string"},
            {"name": "customer_name", "type": "string"},
            {"name": "segment",       "type": "string"},
            {"name": "product_id",    "type": "string"},
            {"name": "product_name",  "type": "string"},
            {"name": "category",      "type": "string"},
            {"name": "quantity",      "type": "int"},
            {"name": "unit_price",    "type": "double"},
            {"name": "total",         "type": "double"},
            {"name": "status",        "type": "string"},
            {"name": "ts",            "type": "string"},
        ],
    },
    "retail-returns": {
        "type": "record", "name": "RetailReturn", "namespace": "com.lab.retail",
        "fields": [
            {"name": "event_id",      "type": "string"},
            {"name": "event_type",    "type": "string"},
            {"name": "customer_id",   "type": "string"},
            {"name": "customer_name", "type": "string"},
            {"name": "segment",       "type": "string"},
            {"name": "product_id",    "type": "string"},
            {"name": "product_name",  "type": "string"},
            {"name": "category",      "type": "string"},
            {"name": "quantity",      "type": "int"},
            {"name": "unit_price",    "type": "double"},
            {"name": "refund_amount", "type": "double"},
            {"name": "reason",        "type": "string"},
            {"name": "ts",            "type": "string"},
        ],
    },
    "retail-browse": {
        "type": "record", "name": "RetailBrowse", "namespace": "com.lab.retail",
        "fields": [
            {"name": "event_id",      "type": "string"},
            {"name": "event_type",    "type": "string"},
            {"name": "customer_id",   "type": "string"},
            {"name": "customer_name", "type": "string"},
            {"name": "segment",       "type": "string"},
            {"name": "product_id",    "type": "string"},
            {"name": "product_name",  "type": "string"},
            {"name": "category",      "type": "string"},
            {"name": "action",        "type": "string"},
            {"name": "ts",            "type": "string"},
        ],
    },

    # ── Transit ───────────────────────────────────────────────────────────────
    "transit-events": {
        "type": "record", "name": "TransitEvent", "namespace": "com.lab.transit",
        "fields": [
            {"name": "event_id",      "type": "string"},
            {"name": "trip_id",       "type": "string"},
            {"name": "route_id",      "type": "string"},
            {"name": "mode",          "type": "string"},
            {"name": "carrier",       "type": "string"},
            {"name": "origin",        "type": "string"},
            {"name": "destination",   "type": "string"},
            {"name": "scheduled_dep", "type": "string"},
            {"name": "status",        "type": "string"},
            {"name": "delay_minutes", "type": "int"},
            {"name": "gate",          "type": "string"},
            {"name": "platform",      "type": "string"},
            {"name": "updated_at",    "type": "string"},
        ],
    },
    "transit-schedules": {
        "type": "record", "name": "TransitSchedule", "namespace": "com.lab.transit",
        "fields": [
            {"name": "trip_id",       "type": "string"},
            {"name": "route_id",      "type": "string"},
            {"name": "mode",          "type": "string"},
            {"name": "carrier",       "type": "string"},
            {"name": "origin",        "type": "string"},
            {"name": "destination",   "type": "string"},
            {"name": "scheduled_dep", "type": "string"},
            {"name": "gate",          "type": "string"},
            {"name": "platform",      "type": "string"},
        ],
    },

    # ── Predictive Maintenance ────────────────────────────────────────────────
    "sensor-readings": {
        "type": "record", "name": "sensorreadings",
        "fields": [
            {"name": "machine_id",  "type": "string"},
            {"name": "sensor_type", "type": "string"},
            {"name": "value",       "type": "double"},
            {"name": "unit",        "type": "string"},
            {"name": "facility",    "type": "string"},
            {"name": "ts",          "type": "string"},
        ],
    },
    "equipment-alerts": {
        "type": "record", "name": "EquipmentAlert", "namespace": "com.lab.pm",
        "fields": [
            {"name": "machine_id",    "type": "string"},
            {"name": "sensor_type",   "type": "string"},
            {"name": "anomaly_score", "type": "double"},
            {"name": "severity",      "type": "string"},
            {"name": "avg_value",     "type": "double"},
            {"name": "window_start",  "type": "string"},
            {"name": "window_end",    "type": "string"},
            {"name": "facility",      "type": "string"},
            {"name": "ts",            "type": "string"},
        ],
    },
    "agent-activity": {
        "type": "record", "name": "AgentActivity", "namespace": "com.lab.pm",
        "fields": [
            {"name": "machine_id",   "type": "string"},
            {"name": "action",       "type": "string"},
            {"name": "work_order_id","type": "string"},
            {"name": "severity",     "type": "string"},
            {"name": "ts",           "type": "string"},
        ],
    },
}


def _register(session, base: str, topic: str, avro_schema: dict, force: bool = False) -> str:
    """Register schema for topic. Returns 'registered', 'exists', or 'error: …'.

    If force=True, hard-deletes any existing versions first so the correct
    schema is always the active one (use after a botched registration).
    """
    subject = f"{topic}-value"

    if force:
        # Hard-delete all existing versions so we can register clean
        session.delete(f"{base}/subjects/{subject}")
        session.delete(f"{base}/subjects/{subject}?permanent=true")

    check = session.get(f"{base}/subjects/{subject}/versions/latest")
    if check.status_code == 200 and not force:
        return "exists"

    payload = {"schema": json.dumps(avro_schema), "schemaType": "AVRO"}
    resp = session.post(
        f"{base}/subjects/{subject}/versions",
        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
        json=payload,
    )
    if resp.status_code in (200, 201):
        return f"registered (id={resp.json().get('id')})"
    return f"error: {resp.status_code} {resp.text[:120]}"


def main():
    parser = argparse.ArgumentParser(description="Register Avro schemas for all lab topics")
    parser.add_argument("--topic", help="Register schema for a single topic only")
    parser.add_argument("--list",  action="store_true", help="List all topics with schemas defined")
    parser.add_argument("--force", action="store_true",
                        help="Hard-delete existing schemas and re-register (fixes botched registrations)")
    args = parser.parse_args()

    if args.list:
        print("Topics with schemas defined:")
        for t in sorted(SCHEMAS):
            print(f"  {t}")
        return

    session, base = http_session("SCHEMA_REGISTRY_URL")

    topics = {args.topic: SCHEMAS[args.topic]} if args.topic else SCHEMAS
    if args.topic and args.topic not in SCHEMAS:
        print(f"✗ No schema defined for topic '{args.topic}'")
        print(f"  Known topics: {', '.join(sorted(SCHEMAS))}")
        sys.exit(1)

    ok = skip = fail = 0
    for topic, schema in topics.items():
        result = _register(session, base, topic, schema, force=args.force)
        if result == "exists":
            print(f"  ─ {topic}-value  already registered")
            skip += 1
        elif result.startswith("registered"):
            print(f"  ✓ {topic}-value  {result}")
            ok += 1
        else:
            print(f"  ✗ {topic}-value  {result}")
            fail += 1

    print(f"\n{'─'*50}")
    print(f"  Registered: {ok}  |  Already existed: {skip}  |  Failed: {fail}")
    if ok + skip > 0:
        print("\nTopics are now queryable in Flink SQL:")
        for topic in topics:
            print(f"  SELECT * FROM `{topic}` LIMIT 10;")


if __name__ == "__main__":
    main()
