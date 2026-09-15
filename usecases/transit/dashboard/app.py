"""
transit/dashboard/app.py — Real-Time Transit Dashboard.

Reads from two Kafka topics:
  • transit-schedules  → planned schedule (seed, read once from earliest)
  • transit-events     → live status updates (on_time / delayed / cancelled)

Features
--------
  • KPI strip: total trips · on-time % · avg delay · cancellations
  • Pipeline architecture diagram (collapsed expander)
  • Live departure board — colour-coded, sorted by scheduled departure
  • Inline scheduler — fires a batch of random status updates every N seconds
  • Auto-refreshes every REFRESH_S seconds

Run
---
    KAFKA_ENV=onprem streamlit run transit/dashboard/app.py

    # Or via the launcher:
    ./transit/run.sh
"""

import json
import os
import random
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
sys.path.insert(0, ".")
from auth import kafka_config
from confluent_kafka import Consumer, KafkaError, Producer
from confluent_kafka.admin import AdminClient, NewTopic

sys.path.insert(0, "usecases/transit")
from topics import (
    TOPIC_EVENTS, TOPIC_SCHEDULES,
    STATUS_ICON, MODE_ICON,
    EVENT_FIELDS,
)
from producer import ROUTES, _delivery_report, _status_update, _make_trip_id, _scheduled_departure

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Transit Live Board — Confluent",
    page_icon="🚆",
    layout="wide",
)

# ── Constants ─────────────────────────────────────────────────────────────────
REFRESH_S   = int(os.getenv("TRANSIT_REFRESH_S", "3"))

# ── Shared process-level event buffer ─────────────────────────────────────────
# cache_resource lives for the lifetime of the server process and is shared
# across all pages, so analytics.py reads the same events as app.py.

@st.cache_resource
def _shared_event_buffer() -> deque:
    return deque(maxlen=500)


# ── Session state ─────────────────────────────────────────────────────────────
if "tr_schedules" not in st.session_state:
    st.session_state.tr_schedules = {}
if "tr_inject"     not in st.session_state:
    st.session_state.tr_inject    = False
if "tr_inj_route"  not in st.session_state:
    st.session_state.tr_inj_route = ROUTES[0]["route_id"]

_scheds = st.session_state.tr_schedules


# ── Background scheduler ──────────────────────────────────────────────────────

class _TransitScheduler:
    """Fires a batch of random transit status updates at a fixed interval."""

    def __init__(self) -> None:
        self._lock     = threading.Lock()
        self._timer: threading.Timer | None = None
        self._interval = 60
        self._running  = False
        self._sent     = 0
        self._last_ts  = ""
        self._error    = ""

    def start(self, interval_s: int) -> None:
        with self._lock:
            if self._running:
                return
            self._interval = interval_s
            self._running  = True
            self._error    = ""
        self._schedule_next()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            if self._timer:
                self._timer.cancel()
                self._timer = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def stats(self) -> dict:
        return {
            "running":  self._running,
            "interval": self._interval,
            "sent":     self._sent,
            "last_ts":  self._last_ts,
            "error":    self._error,
        }

    def _schedule_next(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._timer = threading.Timer(self._interval, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        try:
            cfg = kafka_config(client_id=f"transit-sched-{uuid.uuid4().hex[:6]}")
            cfg.pop("session.timeout.ms", None)
            prod = Producer(cfg)
            sent = 0
            # Publish one status update per route
            for route in ROUTES:
                trip_id   = _make_trip_id(route["route_id"])
                sched_dep = _scheduled_departure(random.randint(0, 120))
                trip = {
                    "trip_id":      trip_id,
                    "route_id":     route["route_id"],
                    "mode":         route["mode"],
                    "carrier":      route["carrier"],
                    "origin":       route["origin"],
                    "destination":  route["destination"],
                    "scheduled_dep": sched_dep,
                }
                event = _status_update(trip)
                prod.produce(
                    TOPIC_EVENTS,
                    key=trip_id.encode(),
                    value=json.dumps(event).encode(),
                    callback=_delivery_report,
                )
                sent += 1
            prod.flush()
            with self._lock:
                self._sent   += sent
                self._last_ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                self._error   = ""
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            self._schedule_next()


@st.cache_resource
def _ensure_topics() -> dict:
    """Create transit topics on the broker if they don't exist yet.
    Returns a status dict shown in the UI.  Cached so it only runs once."""
    results = {}
    try:
        cfg = kafka_config(client_id="transit-admin")
        cfg.pop("session.timeout.ms", None)
        admin = AdminClient(cfg)
        existing = set(admin.list_topics(timeout=10).topics.keys())
        to_create = []
        for topic_name in (TOPIC_SCHEDULES, TOPIC_EVENTS):
            if topic_name not in existing:
                to_create.append(NewTopic(topic_name, num_partitions=3, replication_factor=1))
        if to_create:
            fs = admin.create_topics(to_create)
            for t, f in fs.items():
                try:
                    f.result()
                    results[t] = "created"
                except Exception as e:
                    results[t] = f"error: {e}"
        else:
            for t in (TOPIC_SCHEDULES, TOPIC_EVENTS):
                results[t] = "exists"
    except Exception as e:
        results["error"] = str(e)
    return results


@st.cache_resource
def _get_scheduler() -> _TransitScheduler:
    return _TransitScheduler()


# ── Kafka helpers ─────────────────────────────────────────────────────────────

@st.cache_resource
def _get_events_consumer() -> Consumer:
    cfg = kafka_config(
        client_id="transit-dash-events",
        group_id="transit-dash-events",
    )
    cfg["auto.offset.reset"]  = "earliest"
    cfg["enable.auto.commit"] = False
    cfg["session.timeout.ms"] = 10000
    c = Consumer(cfg)
    c.subscribe([TOPIC_EVENTS])
    return c


@st.cache_resource
def _get_schedules_consumer() -> Consumer:
    cfg = kafka_config(
        client_id=f"transit-sched-{uuid.uuid4().hex[:6]}",
        group_id=f"transit-sched-{uuid.uuid4().hex[:8]}",
    )
    cfg["auto.offset.reset"]  = "earliest"
    cfg["enable.auto.commit"] = False
    cfg["session.timeout.ms"] = 10000
    c = Consumer(cfg)
    c.subscribe([TOPIC_SCHEDULES])
    return c


def _fetch() -> None:
    # Drain schedules (reads from beginning once, then stays idle)
    sched_c = _get_schedules_consumer()
    for _ in range(200):
        msg = sched_c.poll(0.02)
        if msg is None or msg.error():
            break
        try:
            v = json.loads(msg.value().decode("utf-8", errors="replace"))
            _scheds[v["trip_id"]] = v
        except Exception:
            pass

    # Drain live events — longer window on first load (buffer empty = cold start)
    evt_c = _get_events_consumer()
    buf   = _shared_event_buffer()
    drain_secs = 5.0 if len(buf) == 0 else 1.5
    end_t = time.time() + drain_secs
    while time.time() < end_t:
        msg = evt_c.poll(0.05)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                continue
            break
        try:
            v = json.loads(msg.value().decode("utf-8", errors="replace"))
            buf.append(v)
        except Exception:
            pass


# ── DataFrame builder ─────────────────────────────────────────────────────────

def _board_df() -> pd.DataFrame:
    """Latest status per trip_id from the events buffer."""
    buf = _shared_event_buffer()
    if not buf:
        return pd.DataFrame()

    # Keep only the latest event per trip_id
    latest: dict[str, dict] = {}
    for e in buf:
        tid = e.get("trip_id", "")
        if tid:
            latest[tid] = e

    rows = []
    for e in latest.values():
        status = e.get("status", "")
        delay  = int(e.get("delay_minutes", 0) or 0)
        rows.append({
            "Mode":          MODE_ICON.get(e.get("mode", ""), "") + " " + e.get("mode", ""),
            "Route":         e.get("route_id", ""),
            "Carrier":       e.get("carrier", ""),
            "From":          e.get("origin", ""),
            "To":            e.get("destination", ""),
            "Scheduled":     e.get("scheduled_dep", "")[:16].replace("T", " "),
            "Status":        STATUS_ICON.get(status, "⚪") + " " + status.replace("_", " "),
            # None → pd.NA so Arrow sees a nullable int64 column, not mixed str/int
            "Delay (min)":   delay if delay else None,
            "Gate/Platform": e.get("gate") or e.get("platform") or "—",
            "Updated":       e.get("updated_at", "")[:19].replace("T", " "),
            "_status":       status,
            "_delay":        delay,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Cast to nullable integer so Arrow serialises cleanly (None becomes <NA>)
    df["Delay (min)"] = df["Delay (min)"].astype(pd.Int64Dtype())
    df = df.sort_values("Scheduled")
    return df


# ── Pipeline flow diagram ─────────────────────────────────────────────────────

def _render_flow_diagram() -> None:
    svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 180" width="100%" height="180">
  <defs>
    <marker id="arr" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
      <path d="M0,0 L0,6 L8,3 z" fill="#64748b"/>
    </marker>
  </defs>
  <rect width="860" height="180" rx="10" fill="#f8fafc"/>

  <!-- Producer -->
  <rect x="10" y="55" width="130" height="70" rx="8" fill="#dbeafe" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="75" y="80"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="11" font-weight="600" fill="#1e40af">✈️🚆🚌 Transit</text>
  <text x="75" y="95"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" fill="#3b82f6">12 routes</text>
  <text x="75" y="109" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" fill="#3b82f6">flight · train · bus</text>
  <text x="75" y="158" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8"  fill="#94a3b8">transit/producer.py</text>

  <line x1="141" y1="90" x2="173" y2="90" stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>

  <!-- transit-schedules -->
  <rect x="174" y="45" width="140" height="45" rx="8" fill="#dcfce7" stroke="#22c55e" stroke-width="1.5"/>
  <text x="244" y="67"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#15803d">📨 transit-schedules</text>
  <text x="244" y="81"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#16a34a">planned departures</text>

  <!-- transit-events (below) -->
  <rect x="174" y="100" width="140" height="45" rx="8" fill="#fef9c3" stroke="#eab308" stroke-width="1.5"/>
  <text x="244" y="122" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#854d0e">📡 transit-events</text>
  <text x="244" y="136" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#92400e">live status updates</text>

  <text x="244" y="158" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8"  fill="#94a3b8">Confluent Kafka</text>

  <line x1="315" y1="68"  x2="347" y2="68"  stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="315" y1="122" x2="347" y2="122" stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>

  <!-- ksqlDB / Flink -->
  <rect x="348" y="45" width="145" height="100" rx="8" fill="#f0fdf4" stroke="#86efac" stroke-width="1.5"/>
  <text x="420" y="68"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#166534">⚡ ksqlDB / Flink</text>
  <text x="420" y="83"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#15803d">JOIN schedules × events</text>
  <text x="420" y="97"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#15803d">tumbling window avg</text>
  <text x="420" y="111" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#15803d">delay scoring</text>
  <text x="420" y="125" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#15803d">carrier ranking</text>
  <text x="420" y="158" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8"  fill="#94a3b8">(optional enrichment)</text>

  <line x1="494" y1="95" x2="526" y2="95" stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>

  <!-- Dashboard -->
  <rect x="527" y="45" width="145" height="100" rx="8" fill="#f3e8ff" stroke="#a855f7" stroke-width="1.5"/>
  <text x="600" y="68"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#6b21a8">📊 Live Dashboard</text>
  <text x="600" y="83"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#7e22ce">Departure board</text>
  <text x="600" y="97"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#7e22ce">On-time %  ·  Avg delay</text>
  <text x="600" y="111" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#7e22ce">Carrier ranking</text>
  <text x="600" y="125" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#7e22ce">Delay distribution</text>
  <text x="600" y="158" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8"  fill="#94a3b8">transit/dashboard/app.py</text>

  <line x1="673" y1="95" x2="705" y2="95" stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>

  <!-- Alerts -->
  <rect x="706" y="60" width="130" height="70" rx="8" fill="#fee2e2" stroke="#ef4444" stroke-width="1.5"/>
  <text x="771" y="83"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#991b1b">🚨 Alerts</text>
  <text x="771" y="98"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#dc2626">Delay threshold</text>
  <text x="771" y="112" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#dc2626">Cancellation wave</text>
  <text x="771" y="158" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8"  fill="#94a3b8">dashboard sidebar</text>
</svg>
"""
    components.html(svg, height=195, scrolling=False)


# ── Sidebar ────────────────────────────────────────────────────────────────────

def _sidebar() -> tuple[str, str]:
    with st.sidebar:
        st.title("🚆 Transit Live Board")
        st.caption("Confluent Kafka · real-time transit analytics")
        st.divider()

        # ── Filter controls ───────────────────────────────────────────────
        st.subheader("Filters")
        mode_filter   = st.selectbox("Mode",    ["all", "flight", "train", "bus"])
        status_filter = st.selectbox("Status",  ["all", "on_time", "delayed", "cancelled"])

        st.divider()

        # ── Inject delay ──────────────────────────────────────────────────
        st.subheader("🚨 Inject Delay")
        route_opts = [r["route_id"] for r in ROUTES]
        inj_route  = st.selectbox("Route", route_opts)
        if st.button("Inject Delay Now", use_container_width=True, type="primary"):
            st.session_state.tr_inject    = True
            st.session_state.tr_inj_route = inj_route
            st.success(f"Delay wave injected for {inj_route}")

        st.divider()

        # ── Scheduler ─────────────────────────────────────────────────────
        st.subheader("⏱ Event Scheduler")
        sched = _get_scheduler()
        stats = sched.stats

        interval_s = st.select_slider(
            "Interval",
            options=[10, 30, 60, 120, 300],
            value=stats["interval"] if stats["interval"] in [10, 30, 60, 120, 300] else 60,
            format_func=lambda v: {10: "10 sec", 30: "30 sec", 60: "1 min",
                                   120: "2 min", 300: "5 min"}[v],
            disabled=stats["running"],
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("▶ Start", use_container_width=True,
                         disabled=stats["running"], type="primary"):
                sched.start(interval_s)
                st.rerun()
        with c2:
            if st.button("⏹ Stop", use_container_width=True,
                         disabled=not stats["running"]):
                sched.stop()
                st.rerun()

        if stats["running"]:
            st.success(f"🟢 Running · every {stats['interval']}s")
        else:
            st.info("⚪ Stopped")
        if stats["sent"]:
            st.caption(f"Events sent: **{stats['sent']}**")
        if stats["last_ts"]:
            st.caption(f"Last batch: {stats['last_ts']}")
        if stats["error"]:
            st.error(f"Error: {stats['error']}")

        st.divider()
        st.caption(f"Refresh every {REFRESH_S}s")

    return mode_filter, status_filter


# ── Inject delay wave ─────────────────────────────────────────────────────────

def _do_inject(route_id: str) -> None:
    """Publish 20 delayed events for a specific route."""
    try:
        cfg = kafka_config(client_id=f"transit-inject-{uuid.uuid4().hex[:6]}")
        cfg.pop("session.timeout.ms", None)
        prod = Producer(cfg)
        route = next((r for r in ROUTES if r["route_id"] == route_id), ROUTES[0])
        for _ in range(20):
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
            )
        prod.flush()
    except Exception as e:
        st.error(f"Inject failed: {e}")


# ── Main render ───────────────────────────────────────────────────────────────

def render() -> None:
    # Ensure topics exist before any produce/consume (cached — runs once)
    topic_status = _ensure_topics()

    buf = _shared_event_buffer()
    if len(buf) == 0:
        with st.spinner("Loading transit data from Kafka…"):
            _fetch()
    else:
        _fetch()
    mode_filter, status_filter = _sidebar()

    # Handle inject
    if st.session_state.tr_inject:
        st.session_state.tr_inject = False
        route_id = st.session_state.get("tr_inj_route", ROUTES[0]["route_id"])
        _do_inject(route_id)

    # ── Header ────────────────────────────────────────────────────────────────
    st.title("🚆 Real-Time Transit Dashboard")
    st.caption(
        f"Live Kafka streams · {TOPIC_SCHEDULES} · {TOPIC_EVENTS} · "
        f"{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )

    # Topic status banner
    if "error" in topic_status:
        st.error(f"⚠️ Topic setup error: {topic_status['error']}")
    else:
        created = [t for t, s in topic_status.items() if s == "created"]
        if created:
            st.success(f"✅ Topics created: {', '.join(f'`{t}`' for t in created)}")

    with st.expander("🔀 Pipeline Architecture", expanded=False):
        _render_flow_diagram()

    st.divider()

    # ── Build board ───────────────────────────────────────────────────────────
    df = _board_df()

    # Apply filters
    if not df.empty:
        if mode_filter != "all":
            df = df[df["Mode"].str.contains(mode_filter, case=False)]
        if status_filter != "all":
            df = df[df["_status"] == status_filter]

    # ── KPI strip ─────────────────────────────────────────────────────────────
    total      = len(df) if not df.empty else 0
    on_time    = int((df["_status"] == "on_time").sum())    if not df.empty else 0
    delayed    = int((df["_status"] == "delayed").sum())    if not df.empty else 0
    cancelled  = int((df["_status"] == "cancelled").sum())  if not df.empty else 0
    avg_delay  = df.loc[df["_status"] == "delayed", "_delay"].mean() if not df.empty else 0.0
    on_time_pct= round(on_time / total * 100) if total else 0

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Trips",      total)
    k2.metric("🟢 On Time",        on_time, f"{on_time_pct}%")
    k3.metric("🟡 Delayed",        delayed)
    k4.metric("🔴 Cancelled",      cancelled)
    k5.metric("Avg Delay (min)",  f"{avg_delay:.1f}" if avg_delay else "—")

    st.divider()

    # ── Departure board ───────────────────────────────────────────────────────
    st.subheader("🛫 Live Departure Board")

    if df.empty:
        st.info(
            "No transit events yet. Start the scheduler in the sidebar, or run:\n\n"
            "```bash\nKAFKA_ENV=onprem python3 transit/producer.py\n```"
        )
    else:
        display_cols = ["Mode", "Route", "Carrier", "From", "To",
                        "Scheduled", "Status", "Delay (min)", "Gate/Platform", "Updated"]

        # Colour rows by status
        def _row_style(row):
            colour_map = {
                "on_time":   "background-color: #f0fdf4",
                "delayed":   "background-color: #fefce8",
                "cancelled": "background-color: #fef2f2",
            }
            c = colour_map.get(row["_status"], "")
            return [c] * len(row)

        styled = df[display_cols + ["_status"]].style.apply(_row_style, axis=1)
        st.dataframe(
            styled,
            width="stretch",
            hide_index=True,
            height=min(600, 36 + 35 * len(df)),
        )

    st.divider()

    # ── Carrier on-time bar chart ─────────────────────────────────────────────
    if not df.empty and len(df) > 2:
        st.subheader("📊 Carrier On-Time Rate")
        carrier_stats = (
            df.groupby("Carrier")["_status"]
            .apply(lambda s: round((s == "on_time").mean() * 100, 1))
            .reset_index()
        )
        carrier_stats.columns = ["Carrier", "On-Time %"]
        carrier_stats = carrier_stats.sort_values("On-Time %", ascending=False)
        st.bar_chart(carrier_stats.set_index("Carrier"), width="stretch", height=200)

    # ── Auto-refresh ──────────────────────────────────────────────────────────
    time.sleep(REFRESH_S)
    st.rerun()


if __name__ == "__main__":
    render()
