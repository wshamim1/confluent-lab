"""
usecases/retail/producer.py — Retail event simulator.

Produces three event types to Kafka:
  retail-orders   — purchase completed / pending / cancelled
  retail-returns  — item returned with reason
  retail-browse   — page view / add-to-cart

Each customer has a shopping "weight" (vip > premium > regular) and a
configurable inactivity window — some customers are deliberately silent
to trigger reminder campaigns.

Messages are serialised as Avro using the Confluent Schema Registry wire
format (magic byte 0x00 + 4-byte schema ID) so Flink's KafkaCatalog can
deserialise them directly via SELECT.

Run:
    KAFKA_ENV=onprem python3 usecases/retail/producer.py
    KAFKA_ENV=onprem python3 usecases/retail/producer.py --burst 50
"""

import argparse
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, ".")
from auth import kafka_config
from confluent_kafka import Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import SerializationContext, MessageField

sys.path.insert(0, "usecases/retail")
from topics import (
    CUSTOMERS, PRODUCTS, PRODUCT_MAP,
    TOPIC_ORDERS, TOPIC_RETURNS, TOPIC_BROWSE,
    INACTIVE_CUSTOMERS, HIGH_RETURNERS,
)

# ── Avro schemas (must match register_all_schemas.py exactly) ─────────────────
_SCHEMA_ORDERS = """
{
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
    {"name": "ts",            "type": "string"}
  ]
}
"""

_SCHEMA_RETURNS = """
{
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
    {"name": "ts",            "type": "string"}
  ]
}
"""

_SCHEMA_BROWSE = """
{
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
    {"name": "ts",            "type": "string"}
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
        "url":                        sr_url,
        "basic.auth.user.info":       f"{sr_user}:{sr_pass}",
    })


def _make_serializers(sr: SchemaRegistryClient) -> dict:
    """Return per-topic AvroSerializer instances keyed by topic name."""
    return {
        TOPIC_ORDERS:  AvroSerializer(sr, _SCHEMA_ORDERS,  lambda d, _: d),
        TOPIC_RETURNS: AvroSerializer(sr, _SCHEMA_RETURNS, lambda d, _: d),
        TOPIC_BROWSE:  AvroSerializer(sr, _SCHEMA_BROWSE,  lambda d, _: d),
    }

# ── Shopping behaviour weights per segment ────────────────────────────────────
SEGMENT_WEIGHT = {"vip": 6, "premium": 3, "regular": 1}

ORDER_STATUSES = ["completed", "completed", "completed", "pending", "cancelled"]

RETURN_REASONS = [
    "Wrong size", "Defective item", "Changed mind",
    "Not as described", "Found better price", "Damaged in transit",
]

BROWSE_ACTIONS = ["view", "view", "view", "add_to_cart", "wishlist"]


def _delivery_report(err, msg):
    if err:
        print(f"  ✗ delivery error: {err}", file=sys.stderr)


def _producer() -> Producer:
    cfg = kafka_config(client_id=f"retail-producer-{uuid.uuid4().hex[:6]}")
    cfg.pop("session.timeout.ms", None)
    return Producer(cfg)


# ── Module-level SR client + serializers (lazy-initialised once) ──────────────
_sr: SchemaRegistryClient | None = None
_serializers: dict | None = None


def _get_serializers() -> dict:
    global _sr, _serializers
    if _serializers is None:
        _sr = _sr_client()
        _serializers = _make_serializers(_sr)
    return _serializers


def _make_order(customer: dict) -> dict:
    product = random.choice(PRODUCTS)
    qty     = random.randint(1, 4)
    return {
        "event_id":    uuid.uuid4().hex,
        "event_type":  "order",
        "customer_id": customer["customer_id"],
        "customer_name": customer["name"],
        "segment":     customer["segment"],
        "product_id":  product["product_id"],
        "product_name": product["name"],
        "category":    product["category"],
        "quantity":    qty,
        "unit_price":  product["price"],
        "total":       round(product["price"] * qty, 2),
        "status":      random.choice(ORDER_STATUSES),
        "ts":          datetime.now(timezone.utc).isoformat(),
    }


def _make_return(customer: dict) -> dict:
    product = random.choice(PRODUCTS)
    qty     = random.randint(1, 2)
    return {
        "event_id":    uuid.uuid4().hex,
        "event_type":  "return",
        "customer_id": customer["customer_id"],
        "customer_name": customer["name"],
        "segment":     customer["segment"],
        "product_id":  product["product_id"],
        "product_name": product["name"],
        "category":    product["category"],
        "quantity":    qty,
        "unit_price":  product["price"],
        "refund_amount": round(product["price"] * qty, 2),
        "reason":      random.choice(RETURN_REASONS),
        "ts":          datetime.now(timezone.utc).isoformat(),
    }


def _make_browse(customer: dict) -> dict:
    product = random.choice(PRODUCTS)
    return {
        "event_id":    uuid.uuid4().hex,
        "event_type":  "browse",
        "customer_id": customer["customer_id"],
        "customer_name": customer["name"],
        "segment":     customer["segment"],
        "product_id":  product["product_id"],
        "product_name": product["name"],
        "category":    product["category"],
        "action":      random.choice(BROWSE_ACTIONS),
        "ts":          datetime.now(timezone.utc).isoformat(),
    }


def produce_batch(p: Producer, n: int = 10) -> int:
    """Produce n mixed retail events. Returns count produced."""
    serializers = _get_serializers()
    active  = [c for c in CUSTOMERS if c["customer_id"] not in INACTIVE_CUSTOMERS]
    weights = [SEGMENT_WEIGHT[c["segment"]] for c in active]
    count   = 0

    for _ in range(n):
        customer = random.choices(active, weights=weights, k=1)[0]
        roll = random.random()

        if roll < 0.55:
            evt   = _make_order(customer)
            topic = TOPIC_ORDERS
        elif roll < 0.75:
            # High returners return more often
            if customer["customer_id"] in HIGH_RETURNERS:
                evt = _make_return(customer)
            else:
                evt = _make_browse(customer)
            topic = TOPIC_RETURNS if evt["event_type"] == "return" else TOPIC_BROWSE
        else:
            evt   = _make_browse(customer)
            topic = TOPIC_BROWSE

        avro_bytes = serializers[topic](
            evt, SerializationContext(topic, MessageField.VALUE)
        )
        p.produce(
            topic,
            key=customer["customer_id"],
            value=avro_bytes,
            callback=_delivery_report,
        )
        count += 1

    p.flush()
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retail event producer")
    parser.add_argument("--burst", type=int, default=0,
                        help="Produce N events and exit (0 = run continuously)")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Seconds between batches in continuous mode")
    parser.add_argument("--batch", type=int, default=5,
                        help="Events per batch in continuous mode")
    args = parser.parse_args()

    p = _producer()

    if args.burst:
        n = produce_batch(p, args.burst)
        print(f"✓ Produced {n} retail events (burst mode)")
    else:
        print(f"🛍️  Retail producer running (batch={args.batch}, interval={args.interval}s) — Ctrl-C to stop")
        total = 0
        try:
            while True:
                n = produce_batch(p, args.batch)
                total += n
                print(f"  +{n} events  (total: {total})", end="\r")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print(f"\n✓ Stopped. Total events produced: {total}")
