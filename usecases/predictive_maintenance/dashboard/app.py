"""
dashboard/app.py — Streamlit real-time predictive maintenance dashboard.

Reads from three Kafka topics live:
  • sensor-readings   → rolling charts per machine/sensor
  • equipment-alerts  → alert table with anomaly scores
  • agent-activity    → work order log

Run:
    KAFKA_ENV=cloud streamlit run dashboard/app.py

The page auto-refreshes every REFRESH_INTERVAL_S seconds (default: 3).
"""

import json
import os
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, ".")
from auth import kafka_config

from confluent_kafka import Consumer, KafkaError, Producer, TopicPartition

# ── Background sensor scheduler ───────────────────────────────────────────────
# Imported lazily here so sensor_producer stays the single source of truth for
# machine definitions and value generation.
sys.path.insert(0, ".")
from usecases.predictive_maintenance.scripts.sensor_producer import MACHINES, _delivery_report, _make_record, _normal_value


class _Scheduler:
    """Thread-safe repeating scheduler that publishes one batch of sensor
    readings (all machines × all sensors) to Kafka at a fixed interval.

    Stored in st.cache_resource so exactly one instance exists per server
    process, surviving Streamlit reruns and page switches.
    """

    def __init__(self) -> None:
        self._lock     = threading.Lock()
        self._timer: threading.Timer | None = None
        self._interval = 60          # seconds between batches
        self._running  = False
        self._sent     = 0           # total messages produced
        self._last_ts  = ""          # ISO timestamp of last batch
        self._error    = ""          # last producer error, if any

    # ── public API ────────────────────────────────────────────────────────

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

    # ── internals ─────────────────────────────────────────────────────────

    def _schedule_next(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._timer = threading.Timer(self._interval, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        """Produce one reading per sensor per machine, then reschedule."""
        try:
            cfg = kafka_config(client_id=f"scheduler-{uuid.uuid4().hex[:6]}")
            cfg.pop("session.timeout.ms", None)
            prod = Producer(cfg)
            t    = time.time()
            sent = 0
            for machine_id, machine_def in MACHINES.items():
                facility = machine_def["facility"]
                for sensor_type, spec in machine_def["sensors"].items():
                    value  = _normal_value(spec, t)
                    record = _make_record(machine_id, sensor_type, value, spec, facility)
                    prod.produce(
                        "sensor-readings",
                        key=f"{machine_id}:{sensor_type}".encode(),
                        value=json.dumps(record).encode(),
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
def _get_scheduler() -> _Scheduler:
    return _Scheduler()

# ── Config ────────────────────────────────────────────────────────────────────
TOPIC_SENSORS   = "sensor-readings"
TOPIC_ALERTS    = "equipment-alerts"
TOPIC_ACTIVITY  = "agent-activity"
REFRESH_S       = int(os.getenv("DASHBOARD_REFRESH_S", "3"))
MAX_POINTS      = 60   # rolling window per chart series
MAX_ALERTS      = 50
MAX_ACTIVITY    = 30

# ── Streamlit page config ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="Predictive Maintenance — Confluent + WatsonX",
    page_icon="⚙️",
    layout="wide",
)

# ── Session-state cache (persists across Streamlit reruns) ────────────────────
if "sensor_buffer"  not in st.session_state:
    st.session_state.sensor_buffer  = defaultdict(lambda: defaultdict(lambda: deque(maxlen=MAX_POINTS)))
if "alerts_list"    not in st.session_state:
    st.session_state.alerts_list    = deque(maxlen=MAX_ALERTS)
if "activity_list"  not in st.session_state:
    st.session_state.activity_list  = deque(maxlen=MAX_ACTIVITY)
if "last_fetch_ts"  not in st.session_state:
    st.session_state.last_fetch_ts  = 0.0
if "inject_flag"    not in st.session_state:
    st.session_state.inject_flag    = False

# Aliases for shorter references
_sbuf = st.session_state.sensor_buffer
_alrt = st.session_state.alerts_list
_actv = st.session_state.activity_list


# ── Kafka polling helpers ─────────────────────────────────────────────────────

def _make_consumer(topics: list[str]) -> Consumer:
    cfg = kafka_config(
        client_id=f"dashboard-{uuid.uuid4().hex[:6]}",
        group_id=f"dashboard-group-{uuid.uuid4().hex[:8]}",
    )
    cfg["auto.offset.reset"]    = "latest"
    cfg["enable.auto.commit"]   = False
    cfg["session.timeout.ms"]   = 10000
    consumer = Consumer(cfg)
    consumer.subscribe(topics)
    return consumer


def _drain(consumer: Consumer, max_msgs: int = 200, timeout_s: float = 2.0) -> list[dict]:
    """Poll up to max_msgs messages within timeout_s seconds."""
    msgs   = []
    end_t  = time.time() + timeout_s
    while len(msgs) < max_msgs and time.time() < end_t:
        msg = consumer.poll(0.1)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                continue
            break
        try:
            value = json.loads(msg.value().decode("utf-8", errors="replace"))
        except Exception:
            continue
        msgs.append({"topic": msg.topic(), "key": msg.key(), "value": value})
    return msgs


@st.cache_resource
def _get_consumer():
    """Single cached consumer shared across Streamlit reruns."""
    return _make_consumer([TOPIC_SENSORS, TOPIC_ALERTS, TOPIC_ACTIVITY])


def fetch_new_messages() -> None:
    """Drain the shared consumer and update session-state buffers."""
    consumer = _get_consumer()
    msgs     = _drain(consumer, max_msgs=300, timeout_s=1.5)

    for m in msgs:
        v     = m["value"]
        topic = m["topic"]

        if topic == TOPIC_SENSORS:
            mid  = v.get("machine_id", "?")
            stype= v.get("sensor_type","?")
            ts   = v.get("timestamp", datetime.now(timezone.utc).isoformat())
            val  = v.get("value", 0.0)
            _sbuf[mid][stype].append({"ts": ts, "value": val})

        elif topic == TOPIC_ALERTS:
            _alrt.appendleft({
                "detected_at":   v.get("detected_at", ""),
                "machine_id":    v.get("machine_id", "?"),
                "sensor_type":   v.get("sensor_type","?"),
                "severity":      v.get("severity","?"),
                "anomaly_score": round(float(v.get("anomaly_score", 0.0)), 3),
                "avg_value":     round(float(v.get("avg_value", 0.0)), 3),
                "unit":          v.get("unit",""),
                "facility":      v.get("facility","?"),
            })

        elif topic == TOPIC_ACTIVITY:
            payload = v.get("payload", {})
            _actv.appendleft({
                "timestamp":     v.get("timestamp",""),
                "event_type":    v.get("event_type",""),
                "machine_id":    payload.get("machine_id","?"),
                "work_order_id": payload.get("work_order_id",""),
                "url":           payload.get("url",""),
                "notified":      payload.get("notified",""),
                "severity":      payload.get("severity",""),
            })


# ── Severity colour helper ────────────────────────────────────────────────────

def _severity_badge(sev: str) -> str:
    colours = {"critical": "🔴", "warning": "🟡", "info": "🟢"}
    return colours.get(sev.lower(), "⚪") + f" {sev.upper()}"


# ── Inject-anomaly sidebar action ─────────────────────────────────────────────

def _sidebar() -> tuple[str, str]:
    with st.sidebar:
        st.title("⚙️ Predictive Maintenance")
        st.caption("Confluent Cloud + WatsonX Orchestrate")
        st.divider()

        st.subheader("Inject Anomaly")
        machine  = st.selectbox("Machine", ["turbine-1","compressor-1","pump-1","hvac-1"])
        sensor   = st.selectbox("Sensor",  ["vibration","temperature","pressure","flow_rate","rpm"])
        clicked  = st.button("🚨 Inject Anomaly Now", use_container_width=True)

        if clicked:
            st.session_state.inject_flag = True
            st.success(f"Anomaly injected for {machine} / {sensor}")

        st.divider()
        st.metric("Alerts detected",    len(_alrt))
        st.metric("Work orders created", sum(1 for a in _actv if a.get("work_order_id")))
        st.metric("Active machines",    len(_sbuf))

        st.divider()
        st.caption(f"Refresh every {REFRESH_S}s")

        # ── Scheduled producer ────────────────────────────────────────────
        st.divider()
        st.subheader("⏱ Sensor Scheduler")

        sched = _get_scheduler()
        stats = sched.stats

        interval_s = st.select_slider(
            "Interval",
            options=[30, 60, 120, 300],
            value=stats["interval"] if stats["interval"] in [30, 60, 120, 300] else 60,
            format_func=lambda v: {30: "30 sec", 60: "1 min", 120: "2 min", 300: "5 min"}[v],
            disabled=stats["running"],
        )

        col_start, col_stop = st.columns(2)
        with col_start:
            if st.button(
                "▶ Start",
                use_container_width=True,
                disabled=stats["running"],
                type="primary",
            ):
                sched.start(interval_s)
                st.rerun()

        with col_stop:
            if st.button(
                "⏹ Stop",
                use_container_width=True,
                disabled=not stats["running"],
            ):
                sched.stop()
                st.rerun()

        # Status indicator
        if stats["running"]:
            st.success(f"🟢 Running · every {stats['interval']}s")
        else:
            st.info("⚪ Stopped")

        if stats["sent"]:
            st.caption(f"Messages sent: **{stats['sent']}**")
        if stats["last_ts"]:
            st.caption(f"Last batch: {stats['last_ts']}")
        if stats["error"]:
            st.error(f"Error: {stats['error']}")

        return machine, sensor



# ── Pipeline flow diagram ──────────────────────────────────────────────────────

def _render_flow_diagram() -> None:
    """Render an SVG pipeline architecture diagram."""
    svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 200" width="100%" height="200">
  <defs>
    <marker id="arr" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
      <path d="M0,0 L0,6 L8,3 z" fill="#64748b"/>
    </marker>
  </defs>

  <!-- background -->
  <rect width="960" height="200" rx="10" fill="#f8fafc"/>

  <!-- ── Node: IoT Sensors ── -->
  <rect x="10" y="65" width="120" height="70" rx="8" fill="#dbeafe" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="70" y="90" text-anchor="middle" font-family="system-ui,sans-serif" font-size="11" font-weight="600" fill="#1e40af">🔧 IoT Sensors</text>
  <text x="70" y="106" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9" fill="#3b82f6">turbine-1</text>
  <text x="70" y="119" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9" fill="#3b82f6">compressor-1  pump-1  hvac-1</text>

  <!-- arrow 1 -->
  <line x1="131" y1="100" x2="163" y2="100" stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>
  <text x="147" y="93" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8" fill="#94a3b8">JSON</text>

  <!-- ── Node: Kafka topic sensor-readings ── -->
  <rect x="164" y="55" width="140" height="90" rx="8" fill="#dcfce7" stroke="#22c55e" stroke-width="1.5"/>
  <text x="234" y="78" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#15803d">📨 Kafka Topic</text>
  <text x="234" y="93" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="700" fill="#166534">sensor-readings</text>
  <text x="234" y="109" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8.5" fill="#16a34a">SASL_SSL · 3 brokers</text>
  <text x="234" y="123" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8.5" fill="#16a34a">9094 · 9095 · 9096</text>

  <!-- arrow 2 -->
  <line x1="305" y1="100" x2="337" y2="100" stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>
  <text x="321" y="93" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8" fill="#94a3b8">stream</text>

  <!-- ── Node: ksqlDB / Flink ── -->
  <rect x="338" y="55" width="140" height="90" rx="8" fill="#fef9c3" stroke="#eab308" stroke-width="1.5"/>
  <text x="408" y="78" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#854d0e">⚡ ksqlDB / Flink</text>
  <text x="408" y="93" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9" fill="#92400e">Tumbling window 60s</text>
  <text x="408" y="107" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9" fill="#92400e">Z-score anomaly</text>
  <text x="408" y="121" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9" fill="#92400e">detection + scoring</text>
  <text x="408" y="135" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8" fill="#b45309">► run flink_anomaly_setup.py</text>

  <!-- arrow 3 -->
  <line x1="479" y1="100" x2="511" y2="100" stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>
  <text x="495" y="93" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8" fill="#94a3b8">alerts</text>

  <!-- ── Node: Kafka topic equipment-alerts ── -->
  <rect x="512" y="55" width="140" height="90" rx="8" fill="#fee2e2" stroke="#ef4444" stroke-width="1.5"/>
  <text x="582" y="78" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#991b1b">🚨 Kafka Topic</text>
  <text x="582" y="93" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="700" fill="#7f1d1d">equipment-alerts</text>
  <text x="582" y="109" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8.5" fill="#dc2626">anomaly_score</text>
  <text x="582" y="123" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8.5" fill="#dc2626">severity · machine_id</text>

  <!-- arrow 4 -->
  <line x1="653" y1="100" x2="685" y2="100" stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>
  <text x="669" y="93" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8" fill="#94a3b8">MCP</text>

  <!-- ── Node: MCP Agent ── -->
  <rect x="686" y="55" width="120" height="90" rx="8" fill="#f3e8ff" stroke="#a855f7" stroke-width="1.5"/>
  <text x="746" y="78" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#6b21a8">🤖 MCP Agent</text>
  <text x="746" y="93" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9" fill="#7e22ce">WatsonX</text>
  <text x="746" y="107" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9" fill="#7e22ce">Orchestrate</text>
  <text x="746" y="121" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9" fill="#7e22ce">part history</text>
  <text x="746" y="135" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9" fill="#7e22ce">health score</text>

  <!-- arrow 5 -->
  <line x1="807" y1="100" x2="839" y2="100" stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>
  <text x="823" y="93" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8" fill="#94a3b8">Linear</text>

  <!-- ── Node: Work Orders ── -->
  <rect x="840" y="65" width="110" height="70" rx="8" fill="#fff7ed" stroke="#f97316" stroke-width="1.5"/>
  <text x="895" y="90" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#9a3412">📋 Work Orders</text>
  <text x="895" y="106" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9" fill="#c2410c">Linear issues</text>
  <text x="895" y="119" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9" fill="#c2410c">technician notified</text>

  <!-- ── bottom label strip ── -->
  <text x="70"  y="186" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8" fill="#94a3b8">sensor_producer.py</text>
  <text x="234" y="186" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8" fill="#94a3b8">Confluent on-prem VM</text>
  <text x="408" y="186" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8" fill="#94a3b8">flink_anomaly_setup.py</text>
  <text x="582" y="186" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8" fill="#94a3b8">Confluent on-prem VM</text>
  <text x="746" y="186" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8" fill="#94a3b8">mcp_server/server.py</text>
  <text x="895" y="186" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8" fill="#94a3b8">Linear API</text>
</svg>
"""
    components.html(svg, height=215, scrolling=False)



# ── Dashboard layout ──────────────────────────────────────────────────────────

def render() -> None:
    fetch_new_messages()

    machine_filter, sensor_filter = _sidebar()

    # Trigger sensor_producer anomaly injection in a subprocess if requested
    if st.session_state.inject_flag:
        st.session_state.inject_flag = False
        import subprocess
        subprocess.Popen(
            [
                sys.executable,
                "scripts/producers/sensor_producer.py",
                "--inject-anomaly",
                "--machine-id", machine_filter,
                "--sensor-type", sensor_filter,
                "--count", "30",
            ],
            env={**os.environ},
        )

    st.title("⚙️ Real-Time Predictive Maintenance Dashboard")
    st.caption(
        f"Live Kafka streams · "
        f"{TOPIC_SENSORS} · {TOPIC_ALERTS} · {TOPIC_ACTIVITY} · "
        f"last update: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )

    # ── Pipeline flow diagram ─────────────────────────────────────────────
    with st.expander("🔀 Pipeline Architecture", expanded=False):
        _render_flow_diagram()

    st.divider()

    # ── Row 1: KPI strip ──────────────────────────────────────────────────
    total_readings = sum(
        sum(len(v) for v in sensors.values())
        for sensors in _sbuf.values()
    )
    critical_count = sum(1 for a in _alrt if a.get("severity") == "critical")
    warning_count  = sum(1 for a in _alrt if a.get("severity") == "warning")
    wo_count       = sum(1 for a in _actv if a.get("work_order_id"))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Readings",    f"{total_readings:,}")
    c2.metric("🔴 Critical Alerts", critical_count)
    c3.metric("🟡 Warning Alerts",  warning_count)
    c4.metric("📋 Work Orders",     wo_count)

    st.divider()

    # ── Row 2: Sensor charts ──────────────────────────────────────────────
    st.subheader("📊 Sensor Readings")

    if not _sbuf:
        st.info("Waiting for sensor data … start `sensor_producer.py` to see readings.")
    else:
        for machine_id, sensors in sorted(_sbuf.items()):
            with st.expander(f"🔧 {machine_id}", expanded=True):
                cols = st.columns(min(len(sensors), 3))
                for col_idx, (stype, readings_dq) in enumerate(sorted(sensors.items())):
                    readings = list(readings_dq)
                    if not readings:
                        continue
                    col = cols[col_idx % len(cols)]

                    import pandas as pd
                    df = pd.DataFrame(readings)
                    try:
                        df["ts"] = pd.to_datetime(df["ts"], utc=True)
                    except Exception:
                        pass

                    latest = readings[-1]["value"]
                    col.metric(
                        label=stype,
                        value=f"{latest:.2f}",
                        delta=f"{latest - readings[-2]['value']:+.2f}" if len(readings) > 1 else None,
                    )
                    col.line_chart(df.set_index("ts")["value"], use_container_width=True, height=120)

    st.divider()

    # ── Row 3: Equipment alerts ───────────────────────────────────────────
    st.subheader("🚨 Equipment Alerts")

    if not _alrt:
        st.success("No anomalies detected — all systems normal.")
    else:
        import pandas as pd
        df_alerts = pd.DataFrame(list(_alrt))
        df_alerts["severity"] = df_alerts["severity"].apply(_severity_badge)
        st.dataframe(
            df_alerts[[
                "detected_at","machine_id","sensor_type",
                "severity","anomaly_score","avg_value","unit","facility",
            ]],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # ── Row 4: Agent activity / work orders ───────────────────────────────
    st.subheader("🤖 Agent Activity & Work Orders")

    if not _actv:
        st.info("No agent activity yet.")
    else:
        for entry in list(_actv)[:10]:
            url = entry.get("url", "")
            wo  = entry.get("work_order_id", "")
            sev = entry.get("severity", "")
            badge = {"critical":"🔴","warning":"🟡","info":"🟢"}.get(sev,"⚪")

            col_a, col_b = st.columns([3, 1])
            with col_a:
                label = f"{badge} **{entry.get('machine_id','?')}** — WO {wo}"
                st.markdown(label)
                st.caption(
                    f"Notified: {entry.get('notified','')}  |  "
                    f"{entry.get('timestamp','')[:19].replace('T',' ')} UTC"
                )
            with col_b:
                if url:
                    st.link_button("Open in Linear", url, use_container_width=True)

    # ── Auto-refresh ──────────────────────────────────────────────────────
    time.sleep(REFRESH_S)
    st.rerun()


if __name__ == "__main__":
    render()
