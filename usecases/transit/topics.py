"""
transit/topics.py — Shared constants for the transit use-case.

Imported by both the producer and the dashboard so topic names,
field schemas, and helper functions stay in one place.
"""

# ── Topic names ────────────────────────────────────────────────────────────────
TOPIC_SCHEDULES = "transit-schedules"
TOPIC_EVENTS    = "transit-events"

# ── Status palette ─────────────────────────────────────────────────────────────
STATUS_ICON = {
    "on_time":   "🟢",
    "delayed":   "🟡",
    "cancelled": "🔴",
}

STATUS_COLOUR = {
    "on_time":   "#16a34a",
    "delayed":   "#ca8a04",
    "cancelled": "#dc2626",
}

MODE_ICON = {
    "flight": "✈️",
    "train":  "🚆",
    "bus":    "🚌",
}

# ── Expected fields ────────────────────────────────────────────────────────────
SCHEDULE_FIELDS = [
    "trip_id", "route_id", "mode", "carrier",
    "origin", "destination",
    "scheduled_dep", "scheduled_arr",
    "base_duration_min", "created_at",
]

EVENT_FIELDS = [
    "trip_id", "route_id", "mode", "carrier",
    "origin", "destination",
    "scheduled_dep", "status", "delay_minutes",
    "gate", "platform", "updated_at",
]
