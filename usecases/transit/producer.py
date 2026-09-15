"""
transit/producer.py — Simulated transit (flight / train / bus) event producer.

Publishes two streams to Kafka:

  transit-schedules  — one message per trip when the producer starts; contains
                       the full planned schedule (route, carrier, origin,
                       destination, scheduled departure time).

  transit-events     — continuous status updates; each message is a real-time
                       status change (on_time / delayed / cancelled) with an
                       optional delay_minutes value.

Usage
-----
    # Stream events continuously (default: 1 update/sec)
    KAFKA_ENV=onprem python3 transit/producer.py

    # Custom rate and run for a fixed count then exit
    KAFKA_ENV=onprem python3 transit/producer.py --rate 2 --count 200

    # Inject a wave of delays on a specific route
    KAFKA_ENV=onprem python3 transit/producer.py --inject-delay --route NYC-BOS

    # Seed the schedule topic only (no live events)
    KAFKA_ENV=onprem python3 transit/producer.py --seed-only
"""

import argparse
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")
from auth import kafka_config
from confluent_kafka import Producer

# ── Topic names ────────────────────────────────────────────────────────────────
TOPIC_SCHEDULES = "transit-schedules"
TOPIC_EVENTS    = "transit-events"

# ── Fleet catalogue ───────────────────────────────────────────────────────────
# Each entry: route_id, mode, carrier, origin, destination, base_duration_min
ROUTES = [
    {"route_id": "AA-101",  "mode": "flight", "carrier": "American Airlines", "origin": "JFK", "destination": "LAX", "base_duration_min": 330},
    {"route_id": "AA-202",  "mode": "flight", "carrier": "American Airlines", "origin": "LAX", "destination": "ORD", "base_duration_min": 240},
    {"route_id": "UA-301",  "mode": "flight", "carrier": "United Airlines",   "origin": "SFO", "destination": "JFK", "base_duration_min": 320},
    {"route_id": "UA-405",  "mode": "flight", "carrier": "United Airlines",   "origin": "ORD", "destination": "MIA", "base_duration_min": 190},
    {"route_id": "DL-512",  "mode": "flight", "carrier": "Delta",             "origin": "ATL", "destination": "BOS", "base_duration_min": 170},
    {"route_id": "DL-618",  "mode": "flight", "carrier": "Delta",             "origin": "BOS", "destination": "SEA", "base_duration_min": 360},
    {"route_id": "NJ-101",  "mode": "train",  "carrier": "NJ Transit",        "origin": "Newark", "destination": "New York Penn", "base_duration_min": 25},
    {"route_id": "NJ-202",  "mode": "train",  "carrier": "NJ Transit",        "origin": "Trenton", "destination": "New York Penn", "base_duration_min": 65},
    {"route_id": "AMTK-1",  "mode": "train",  "carrier": "Amtrak",            "origin": "Washington DC", "destination": "New York Penn", "base_duration_min": 195},
    {"route_id": "AMTK-2",  "mode": "train",  "carrier": "Amtrak",            "origin": "New York Penn", "destination": "Boston South", "base_duration_min": 215},
    {"route_id": "MTA-M1",  "mode": "bus",    "carrier": "MTA",               "origin": "Midtown",  "destination": "JFK Airport",   "base_duration_min": 60},
    {"route_id": "MTA-M2",  "mode": "bus",    "carrier": "MTA",               "origin": "Downtown", "destination": "LaGuardia",      "base_duration_min": 45},
]

# ── Probability weights per mode ──────────────────────────────────────────────
# (on_time, delayed, cancelled)
MODE_WEIGHTS = {
    "flight": (0.68, 0.27, 0.05),
    "train":  (0.75, 0.22, 0.03),
    "bus":    (0.60, 0.35, 0.05),
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scheduled_departure(offset_min: int = 0) -> str:
    """Return a departure time offset_min minutes from now."""
    t = datetime.now(timezone.utc) + timedelta(minutes=offset_min)
    return t.isoformat()


def _make_trip_id(route_id: str) -> str:
    return f"{route_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{random.randint(100,999)}"


def _delivery_report(err, msg):
    if err:
        print(f"  ✗ delivery failed: {err}", file=sys.stderr)


# ── Schedule seeding ──────────────────────────────────────────────────────────

def seed_schedules(prod: Producer) -> list[dict]:
    """
    Publish one schedule event per route for the next 4 hours,
    spaced ~10 minutes apart.  Returns the list of trips created.
    """
    trips = []
    offset = 0
    for route in ROUTES:
        trip_id  = _make_trip_id(route["route_id"])
        sched_dep = _scheduled_departure(offset)
        sched_arr = _scheduled_departure(offset + route["base_duration_min"])
        record = {
            "trip_id":          trip_id,
            "route_id":         route["route_id"],
            "mode":             route["mode"],
            "carrier":          route["carrier"],
            "origin":           route["origin"],
            "destination":      route["destination"],
            "scheduled_dep":    sched_dep,
            "scheduled_arr":    sched_arr,
            "base_duration_min": route["base_duration_min"],
            "created_at":       _now_iso(),
        }
        prod.produce(
            TOPIC_SCHEDULES,
            key=trip_id.encode(),
            value=json.dumps(record).encode(),
            callback=_delivery_report,
        )
        trips.append({**record, **route})
        offset += random.randint(8, 15)   # stagger departures
        print(f"  📋  scheduled  {trip_id:<30}  {route['origin']} → {route['destination']}")

    prod.flush()
    print(f"\n[transit] {len(trips)} trips seeded to '{TOPIC_SCHEDULES}'")
    return trips


# ── Live status updates ───────────────────────────────────────────────────────

def _status_update(trip: dict, force_delay: bool = False) -> dict:
    """Generate a random status update for a trip."""
    weights = MODE_WEIGHTS.get(trip["mode"], (0.7, 0.25, 0.05))
    if force_delay:
        status = "delayed"
    else:
        status = random.choices(["on_time", "delayed", "cancelled"], weights=weights)[0]

    delay_minutes = 0
    if status == "delayed":
        delay_minutes = random.choices(
            [5, 10, 15, 20, 30, 45, 60, 90],
            weights=[20, 20, 18, 15, 12, 8, 5, 2],
        )[0]

    return {
        "trip_id":      trip["trip_id"],
        "route_id":     trip["route_id"],
        "mode":         trip["mode"],
        "carrier":      trip["carrier"],
        "origin":       trip["origin"],
        "destination":  trip["destination"],
        "scheduled_dep": trip["scheduled_dep"],
        "status":       status,
        "delay_minutes": delay_minutes,
        "gate":         f"{random.choice('ABCDEFGH')}{random.randint(1,40)}" if trip["mode"] == "flight" else "",
        "platform":     str(random.randint(1, 12)) if trip["mode"] == "train" else "",
        "updated_at":   _now_iso(),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    cfg = kafka_config(client_id="transit-producer")
    cfg.pop("session.timeout.ms", None)
    prod = Producer(cfg)

    print(f"[transit] Seeding schedule for {len(ROUTES)} routes …")
    trips = seed_schedules(prod)

    if args.seed_only:
        print("[transit] --seed-only set — done.")
        return

    print(f"\n[transit] Publishing live updates to '{TOPIC_EVENTS}' — Ctrl-C to stop\n")

    count   = 0
    t0      = time.time()

    try:
        while True:
            # Pick a random trip and generate a status update
            trip = random.choice(trips)
            force = args.inject_delay and trip["route_id"] == args.route
            event = _status_update(trip, force_delay=force)

            prod.produce(
                TOPIC_EVENTS,
                key=event["trip_id"].encode(),
                value=json.dumps(event).encode(),
                callback=_delivery_report,
            )

            icon = {"on_time": "🟢", "delayed": "🟡", "cancelled": "🔴"}.get(event["status"], "⚪")
            delay_str = f"  +{event['delay_minutes']}min" if event["delay_minutes"] else ""
            print(
                f"  {icon}  {event['route_id']:<10}  {event['origin']:<22} → {event['destination']:<22}"
                f"  {event['status']}{delay_str}"
            )

            count += 1
            prod.poll(0)

            if args.count and count >= args.count:
                break

            time.sleep(1.0 / max(args.rate, 0.1))

    except KeyboardInterrupt:
        print("\n[transit] Stopped by user.")
    finally:
        prod.flush()
        elapsed = round(time.time() - t0, 1)
        print(f"[transit] Done — {count} events in {elapsed}s")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Transit event producer")
    p.add_argument("--rate",         type=float, default=1.0,
                   help="Updates per second (default: 1.0)")
    p.add_argument("--count",        type=int, default=0,
                   help="Stop after N events (0 = run forever)")
    p.add_argument("--seed-only",    action="store_true",
                   help="Seed schedules then exit without streaming events")
    p.add_argument("--inject-delay", action="store_true",
                   help="Force delays on a specific route")
    p.add_argument("--route",        default="AA-101",
                   help="Route to inject delays on (default: AA-101)")
    return p.parse_args()


if __name__ == "__main__":
    run(_parse())
