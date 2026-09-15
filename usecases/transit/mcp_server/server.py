"""
usecases/transit/mcp_server/server.py — MCP server for the Transit use-case.

Exposes six tools to any MCP-compatible agent (Bob, WatsonX Orchestrate, etc.):

  transit_read_events      — Read the latest N events from transit-events topic
  transit_get_route_status — Current on-time / delayed / cancelled summary for a route
  transit_get_delayed_trips — All currently delayed trips, optionally filtered by mode
  transit_inject_delay     — Produce a wave of delay events for a specific route
  transit_get_carrier_stats — On-time %, avg delay, cancellation rate per carrier
  transit_get_trip_detail  — Full detail for a specific trip_id

Run (stdio transport — for use with Bob MCP config):
    KAFKA_ENV=onprem python3 usecases/transit/mcp_server/server.py

Environment variables (loaded from .env):
    KAFKA_ENV               cloud | onprem
    VM_BOOTSTRAP_SERVERS    (onprem) or KAFKA_BOOTSTRAP_SERVERS (cloud)
    VM_SASL_USERNAME / VM_SASL_PASSWORD  (onprem)
    CONFLUENT_CLOUD_API_KEY / CONFLUENT_CLOUD_API_SECRET (cloud)
"""

import json
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

sys.path.insert(0, ".")
from auth import kafka_config

from confluent_kafka import Consumer, KafkaError, Producer, TopicPartition
from dotenv import load_dotenv

load_dotenv()

# ── MCP SDK ───────────────────────────────────────────────────────────────────
from mcp.server.mcpserver import MCPServer as FastMCP

# ── Topics ────────────────────────────────────────────────────────────────────
TOPIC_EVENTS    = "transit-events"
TOPIC_SCHEDULES = "transit-schedules"
DEFAULT_LIMIT   = 20

# ── Route catalogue (mirrors producer.py) ─────────────────────────────────────
sys.path.insert(0, "usecases/transit")
from producer import ROUTES, _status_update, _make_trip_id, _scheduled_departure, _delivery_report

# ── Kafka helpers ─────────────────────────────────────────────────────────────

def _consumer(topic: str, limit: int, from_beginning: bool = False) -> list[dict]:
    """Read up to `limit` messages from `topic`."""
    cfg = kafka_config(client_id=f"transit-mcp-{uuid.uuid4().hex[:6]}",
                       group_id=f"transit-mcp-{uuid.uuid4().hex[:8]}")
    cfg["auto.offset.reset"]  = "earliest" if from_beginning else "latest"
    cfg["enable.auto.commit"] = False
    cfg["session.timeout.ms"] = 10000
    c = Consumer(cfg)

    # Fetch metadata for the correct topic
    meta  = c.list_topics(topic, timeout=10)
    parts = [TopicPartition(topic, p)
             for p in meta.topics[topic].partitions.keys()]
    if not parts:
        c.close()
        return []

    if not from_beginning:
        # Seek each partition to max(0, high_watermark - limit) to read the tail
        tail_parts = []
        for tp in parts:
            lo, hi_off = c.get_watermark_offsets(tp, timeout=5)
            start = max(lo, hi_off - limit)
            tail_parts.append(TopicPartition(tp.topic, tp.partition, start))
        c.assign(tail_parts)
    else:
        c.assign(parts)

    msgs    = []
    empties = 0
    max_empties = 6 if from_beginning else 3   # more tolerance for remote broker
    while len(msgs) < limit and empties < max_empties:
        msg = c.poll(1.0)
        if msg is None:
            empties += 1
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                break
            continue
        empties = 0
        try:
            msgs.append(json.loads(msg.value().decode("utf-8", errors="replace")))
        except Exception:
            pass
    c.close()
    return msgs


def _producer() -> Producer:
    cfg = kafka_config(client_id=f"transit-mcp-prod-{uuid.uuid4().hex[:6]}")
    cfg.pop("session.timeout.ms", None)
    return Producer(cfg)


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP("transit-mcp-server")

TOOLS = [
    {
        "name":        "transit_read_events",
        "description": "Read the latest transit status events from the transit-events Kafka topic. Returns trip_id, route, carrier, status (on_time/delayed/cancelled), delay_minutes, and gate/platform.",
    },
    {
        "name":        "transit_get_route_status",
        "description": "Get the current on-time/delayed/cancelled summary for a specific route (e.g. AA-101, UA-301, NJ-101). Returns counts and the latest trip statuses.",
    },
    {
        "name":        "transit_get_delayed_trips",
        "description": "Return all currently delayed trips from the event stream, optionally filtered by mode (flight/train/bus). Includes delay_minutes and gate/platform.",
    },
    {
        "name":        "transit_inject_delay",
        "description": "Inject a wave of delay events into the transit-events Kafka topic for a specific route. Use for testing or simulating disruptions.",
    },
    {
        "name":        "transit_get_carrier_stats",
        "description": "Compute on-time percentage, average delay, and cancellation rate per carrier from the latest events. Returns a ranked table.",
    },
    {
        "name":        "transit_get_trip_detail",
        "description": "Get full detail for a specific trip_id from the event stream.",
    },
]


# ── Tool implementations ──────────────────────────────────────────────────────

def tool_transit_read_events(params: dict) -> str:
    limit = int(params.get("limit", DEFAULT_LIMIT))
    msgs  = _consumer(TOPIC_EVENTS, limit, from_beginning=True)
    return json.dumps({
        "topic": TOPIC_EVENTS,
        "count": len(msgs),
        "events": msgs,
    })


def tool_transit_get_route_status(params: dict) -> str:
    route_id = params.get("route_id", "").upper()
    if not route_id:
        return json.dumps({"error": "route_id is required"})

    all_msgs = _consumer(TOPIC_EVENTS, 500, from_beginning=True)

    # Latest event per trip on this route
    latest: dict[str, dict] = {}
    for m in all_msgs:
        if m.get("route_id", "").upper() == route_id:
            latest[m["trip_id"]] = m

    if not latest:
        return json.dumps({"route_id": route_id, "message": "No events found for this route"})

    trips   = list(latest.values())
    on_time    = [t for t in trips if t.get("status") == "on_time"]
    delayed    = [t for t in trips if t.get("status") == "delayed"]
    cancelled  = [t for t in trips if t.get("status") == "cancelled"]
    avg_delay  = (sum(int(t.get("delay_minutes", 0) or 0) for t in delayed)
                  / len(delayed)) if delayed else 0

    # Get route info from catalogue
    route_info = next((r for r in ROUTES if r["route_id"] == route_id), {})

    return json.dumps({
        "route_id":     route_id,
        "carrier":      route_info.get("carrier", "Unknown"),
        "mode":         route_info.get("mode", "unknown"),
        "origin":       route_info.get("origin", ""),
        "destination":  route_info.get("destination", ""),
        "total_trips":  len(trips),
        "on_time":      len(on_time),
        "delayed":      len(delayed),
        "cancelled":    len(cancelled),
        "on_time_pct":  round(len(on_time) / len(trips) * 100, 1) if trips else 0,
        "avg_delay_min": round(avg_delay, 1),
        "latest_trips": trips[:5],
    })


def tool_transit_get_delayed_trips(params: dict) -> str:
    mode    = params.get("mode", "").lower()
    limit   = int(params.get("limit", 50))

    all_msgs = _consumer(TOPIC_EVENTS, 500, from_beginning=True)

    # Latest status per trip
    latest: dict[str, dict] = {}
    for m in all_msgs:
        latest[m["trip_id"]] = m

    delayed = [
        t for t in latest.values()
        if t.get("status") == "delayed"
        and (not mode or t.get("mode", "") == mode)
    ]
    delayed.sort(key=lambda t: int(t.get("delay_minutes", 0) or 0), reverse=True)

    return json.dumps({
        "mode_filter":   mode or "all",
        "delayed_count": len(delayed),
        "trips":         delayed[:limit],
    })


def tool_transit_inject_delay(params: dict) -> str:
    route_id = params.get("route_id", "AA-101").upper()
    count    = min(int(params.get("count", 10)), 30)

    route = next((r for r in ROUTES if r["route_id"] == route_id), ROUTES[0])
    prod  = _producer()
    sent  = 0
    for _ in range(count):
        trip_id = _make_trip_id(route["route_id"])
        trip = {
            "trip_id":       trip_id,
            "route_id":      route["route_id"],
            "mode":          route["mode"],
            "carrier":       route["carrier"],
            "origin":        route["origin"],
            "destination":   route["destination"],
            "scheduled_dep": _scheduled_departure(random.randint(0, 60)),
        }
        event = _status_update(trip, force_delay=True)
        prod.produce(
            TOPIC_EVENTS,
            key=trip_id.encode(),
            value=json.dumps(event).encode(),
            callback=_delivery_report,
        )
        sent += 1
    prod.flush()

    return json.dumps({
        "status":   "injected",
        "route_id": route_id,
        "carrier":  route["carrier"],
        "events_produced": sent,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def tool_transit_get_carrier_stats(params: dict) -> str:
    all_msgs = _consumer(TOPIC_EVENTS, 500, from_beginning=True)

    # Latest status per trip
    latest: dict[str, dict] = {}
    for m in all_msgs:
        latest[m["trip_id"]] = m

    # Aggregate per carrier
    stats: dict[str, dict] = {}
    for t in latest.values():
        carrier = t.get("carrier", "Unknown")
        if carrier not in stats:
            stats[carrier] = {"total": 0, "on_time": 0, "delayed": 0,
                              "cancelled": 0, "delay_sum": 0}
        s = stats[carrier]
        s["total"] += 1
        status = t.get("status", "")
        if status == "on_time":
            s["on_time"] += 1
        elif status == "delayed":
            s["delayed"] += 1
            s["delay_sum"] += int(t.get("delay_minutes", 0) or 0)
        elif status == "cancelled":
            s["cancelled"] += 1

    result = []
    for carrier, s in stats.items():
        result.append({
            "carrier":      carrier,
            "total_trips":  s["total"],
            "on_time":      s["on_time"],
            "delayed":      s["delayed"],
            "cancelled":    s["cancelled"],
            "on_time_pct":  round(s["on_time"] / s["total"] * 100, 1) if s["total"] else 0,
            "avg_delay_min": round(s["delay_sum"] / s["delayed"], 1) if s["delayed"] else 0,
        })

    result.sort(key=lambda x: x["on_time_pct"], reverse=True)
    return json.dumps({"carriers": result, "total_trips": sum(s["total"] for s in stats.values())})


def tool_transit_get_trip_detail(params: dict) -> str:
    trip_id = params.get("trip_id", "")
    if not trip_id:
        return json.dumps({"error": "trip_id is required"})

    all_msgs = _consumer(TOPIC_EVENTS, 500, from_beginning=True)
    trips = [m for m in all_msgs if m.get("trip_id") == trip_id]

    if not trips:
        return json.dumps({"trip_id": trip_id, "message": "Trip not found"})

    return json.dumps({"trip_id": trip_id, "events": trips, "latest": trips[-1]})


# ── MCP tool wrappers ─────────────────────────────────────────────────────────

@mcp.tool(description=TOOLS[0]["description"])
def transit_read_events(limit: int = DEFAULT_LIMIT) -> str:
    return tool_transit_read_events({"limit": limit})

@mcp.tool(description=TOOLS[1]["description"])
def transit_get_route_status(route_id: str) -> str:
    return tool_transit_get_route_status({"route_id": route_id})

@mcp.tool(description=TOOLS[2]["description"])
def transit_get_delayed_trips(mode: str = "", limit: int = 50) -> str:
    return tool_transit_get_delayed_trips({"mode": mode, "limit": limit})

@mcp.tool(description=TOOLS[3]["description"])
def transit_inject_delay(route_id: str = "AA-101", count: int = 10) -> str:
    return tool_transit_inject_delay({"route_id": route_id, "count": count})

@mcp.tool(description=TOOLS[4]["description"])
def transit_get_carrier_stats() -> str:
    return tool_transit_get_carrier_stats({})

@mcp.tool(description=TOOLS[5]["description"])
def transit_get_trip_detail(trip_id: str) -> str:
    return tool_transit_get_trip_detail({"trip_id": trip_id})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
