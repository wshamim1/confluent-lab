"""
dashboard/pages/flink_analytics.py — Flink-style analytics over live Kafka data.

Reads a rolling snapshot of sensor-readings and equipment-alerts, then applies
SQL-style transforms (via pandas) to produce four live charts:

  ┌──────────────────────────┬──────────────────────────┐
  │  Rolling avg per sensor  │  Anomaly score histogram │
  ├──────────────────────────┼──────────────────────────┤
  │  Alert severity mix      │  Per-machine health map  │
  └──────────────────────────┴──────────────────────────┘

A live Query Activity section below the charts shows every SQL transform that
ran this session: query name, SQL text, execution time (ms), rows returned,
and timestamp — so you can see exactly what is being executed.

Run alongside the main dashboard:
    KAFKA_ENV=onprem streamlit run dashboard/app.py
"""

import contextlib
import json
import os
import sys
import time
import uuid
from collections import deque
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

sys.path.insert(0, ".")
from auth import kafka_config
from confluent_kafka import Consumer, KafkaError

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Flink Analytics — Predictive Maintenance",
    page_icon="⚡",
    layout="wide",
)

# ── Constants ─────────────────────────────────────────────────────────────────
TOPIC_SENSORS  = "sensor-readings"
TOPIC_ALERTS   = "equipment-alerts"
REFRESH_S      = int(os.getenv("DASHBOARD_REFRESH_S", "4"))
BUFFER_SIZE    = 500   # max raw events kept in rolling buffer
MAX_LOG        = 50    # max query log entries kept in session

# Thresholds used in the "health" transform (mirrors Flink anomaly detector logic)
THRESHOLDS = {
    "temperature": 300.0,
    "vibration":   10.0,
    "pressure":    120.0,
    "flow_rate":   50.0,
    "rpm":         3500.0,
}

# SQL strings — single source of truth, referenced by both log entries and
# the inline code blocks rendered beside each chart.
SQL = {
    "rolling_avg": """\
SELECT
    sensor_type,
    TUMBLE_START(proc_time, INTERVAL '30' SECOND) AS window_start,
    AVG(`value`)                                  AS avg_value,
    MIN(`value`)                                  AS min_value,
    MAX(`value`)                                  AS max_value,
    COUNT(*)                                      AS reading_count
FROM sensor_readings
GROUP BY
    sensor_type,
    TUMBLE(proc_time, INTERVAL '30' SECOND);""",

    "anomaly_scores": """\
SELECT
    CASE
        WHEN anomaly_score < 1.5  THEN 'low    (< 1.5)'
        WHEN anomaly_score < 2.5  THEN 'medium (1.5–2.5)'
        WHEN anomaly_score < 4.0  THEN 'high   (2.5–4.0)'
        ELSE                           'critical (≥ 4.0)'
    END AS score_bucket,
    COUNT(*) AS alert_count
FROM equipment_alerts_view
GROUP BY
    CASE
        WHEN anomaly_score < 1.5  THEN 'low    (< 1.5)'
        WHEN anomaly_score < 2.5  THEN 'medium (1.5–2.5)'
        WHEN anomaly_score < 4.0  THEN 'high   (2.5–4.0)'
        ELSE                           'critical (≥ 4.0)'
    END;""",

    "severity_mix": """\
SELECT
    severity,
    sensor_type,
    COUNT(*)           AS alert_count,
    AVG(anomaly_score) AS avg_score
FROM equipment_alerts_view
GROUP BY severity, sensor_type
ORDER BY alert_count DESC;""",

    "machine_health": """\
SELECT
    machine_id,
    sensor_type,
    LAST_VALUE(`value`) OVER w AS latest_value,
    CASE
        WHEN sensor_type = 'temperature' AND LAST_VALUE(`value`) OVER w > 300  THEN 'critical'
        WHEN sensor_type = 'vibration'   AND LAST_VALUE(`value`) OVER w > 10   THEN 'critical'
        WHEN sensor_type = 'pressure'    AND LAST_VALUE(`value`) OVER w > 120  THEN 'critical'
        WHEN sensor_type = 'rpm'         AND LAST_VALUE(`value`) OVER w > 3500 THEN 'critical'
        WHEN sensor_type = 'flow_rate'   AND LAST_VALUE(`value`) OVER w > 50   THEN 'critical'
        ELSE 'normal'
    END AS health_status
FROM sensor_readings
WINDOW w AS (
    PARTITION BY machine_id, sensor_type
    ORDER BY proc_time
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
);""",
}

# Human-readable labels for each query key
QUERY_LABELS = {
    "rolling_avg":    "Rolling Avg by Sensor",
    "anomaly_scores": "Anomaly Score Buckets",
    "severity_mix":   "Severity × Sensor Pivot",
    "machine_health": "Machine Health Snapshot",
}

# ── Session state ─────────────────────────────────────────────────────────────
if "fa_sensors"   not in st.session_state:
    st.session_state.fa_sensors  = deque(maxlen=BUFFER_SIZE)
if "fa_alerts"    not in st.session_state:
    st.session_state.fa_alerts   = deque(maxlen=200)
if "fa_fetch_ts"  not in st.session_state:
    st.session_state.fa_fetch_ts = 0.0
if "fa_query_log" not in st.session_state:
    # Each entry: {query, label, sql, duration_ms, rows, ts, status}
    st.session_state.fa_query_log = deque(maxlen=MAX_LOG)

_sbuf    = st.session_state.fa_sensors
_abuf    = st.session_state.fa_alerts
_qlog    = st.session_state.fa_query_log


# ── Query logger ──────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _log_query(query_key: str):
    """Context manager that times a transform block and appends a log entry."""
    t0 = time.perf_counter()
    result_holder: dict = {"rows": 0, "status": "ok", "error": ""}
    try:
        yield result_holder
    except Exception as exc:
        result_holder["status"] = "error"
        result_holder["error"]  = str(exc)
        raise
    finally:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        _qlog.appendleft({
            "query":       query_key,
            "label":       QUERY_LABELS.get(query_key, query_key),
            "sql":         SQL.get(query_key, ""),
            "duration_ms": elapsed_ms,
            "rows":        result_holder["rows"],
            "status":      result_holder["status"],
            "error":       result_holder["error"],
            "ts":          datetime.now(timezone.utc).strftime("%H:%M:%S"),
        })


# ── Kafka helpers ─────────────────────────────────────────────────────────────

@st.cache_resource
def _get_consumer() -> Consumer:
    cfg = kafka_config(
        client_id=f"flink-analytics-{uuid.uuid4().hex[:6]}",
        group_id=f"flink-analytics-group-{uuid.uuid4().hex[:8]}",
    )
    cfg["auto.offset.reset"]  = "latest"
    cfg["enable.auto.commit"] = False
    cfg["session.timeout.ms"] = 10000
    c = Consumer(cfg)
    c.subscribe([TOPIC_SENSORS, TOPIC_ALERTS])
    return c


def _fetch() -> None:
    """Drain the consumer and append raw events to the rolling buffers."""
    consumer = _get_consumer()
    end_t    = time.time() + 1.5
    count    = 0
    while count < 400 and time.time() < end_t:
        msg = consumer.poll(0.05)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                continue
            break
        try:
            v = json.loads(msg.value().decode("utf-8", errors="replace"))
        except Exception:
            continue
        if msg.topic() == TOPIC_SENSORS:
            _sbuf.append(v)
        else:
            _abuf.append(v)
        count += 1
    st.session_state.fa_fetch_ts = time.time()


# ── DataFrame builders ────────────────────────────────────────────────────────

def _sensors_df() -> pd.DataFrame:
    if not _sbuf:
        return pd.DataFrame()
    df = pd.DataFrame(list(_sbuf))
    if df.empty:
        return df
    for col in ("machine_id", "sensor_type", "value", "unit", "facility", "timestamp"):
        if col not in df.columns:
            df[col] = None
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    try:
        df["ts"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    except Exception:
        df["ts"] = pd.NaT
    return df.dropna(subset=["value"])


def _alerts_df() -> pd.DataFrame:
    if not _abuf:
        return pd.DataFrame()
    df = pd.DataFrame(list(_abuf))
    for col in ("machine_id", "sensor_type", "anomaly_score", "severity", "facility", "detected_at"):
        if col not in df.columns:
            df[col] = None
    df["anomaly_score"] = pd.to_numeric(df["anomaly_score"], errors="coerce").fillna(0.0)
    return df


# ── Chart renderers ───────────────────────────────────────────────────────────

def _chart_rolling_avg(df: pd.DataFrame) -> None:
    st.subheader("📈 Rolling Average by Sensor Type")

    with st.expander("🔍 Flink SQL", expanded=False):
        st.code(SQL["rolling_avg"], language="sql")

    if df.empty:
        st.info("Waiting for sensor data…")
        return

    with _log_query("rolling_avg") as ctx:
        agg = (
            df.groupby("sensor_type")["value"]
            .agg(avg_value="mean", count="count", min_value="min", max_value="max")
            .reset_index()
            .sort_values("avg_value", ascending=False)
        )
        agg["avg_value"] = agg["avg_value"].round(2)
        agg["min_value"] = agg["min_value"].round(2)
        agg["max_value"] = agg["max_value"].round(2)
        ctx["rows"] = len(agg)

    st.bar_chart(agg.set_index("sensor_type")[["avg_value"]], use_container_width=True, height=200)
    st.dataframe(
        agg.rename(columns={
            "sensor_type": "Sensor", "avg_value": "Avg",
            "count": "Readings", "min_value": "Min", "max_value": "Max",
        }),
        use_container_width=True, hide_index=True,
    )


def _chart_anomaly_scores(df_alerts: pd.DataFrame) -> None:
    st.subheader("🎯 Anomaly Score Distribution")

    with st.expander("🔍 Flink SQL", expanded=False):
        st.code(SQL["anomaly_scores"], language="sql")

    if df_alerts.empty:
        st.info("No alert data yet — inject an anomaly to populate.")
        return

    with _log_query("anomaly_scores") as ctx:
        bins   = [0.0, 1.5, 2.5, 4.0, float("inf")]
        labels = ["low (<1.5)", "medium (1.5–2.5)", "high (2.5–4.0)", "critical (≥4.0)"]
        df2    = df_alerts.copy()
        df2["bucket"] = pd.cut(df2["anomaly_score"], bins=bins, labels=labels, right=False)
        counts = (
            df2["bucket"].value_counts()
            .reindex(labels, fill_value=0)
            .reset_index()
        )
        counts.columns = ["Score bucket", "Count"]
        ctx["rows"] = len(counts)

    st.bar_chart(counts.set_index("Score bucket"), use_container_width=True, height=200)


def _chart_severity_mix(df_alerts: pd.DataFrame) -> None:
    st.subheader("🚦 Alerts by Severity × Sensor")

    with st.expander("🔍 Flink SQL", expanded=False):
        st.code(SQL["severity_mix"], language="sql")

    if df_alerts.empty:
        st.info("No alert data yet.")
        return

    with _log_query("severity_mix") as ctx:
        pivot = (
            df_alerts.groupby(["severity", "sensor_type"])
            .size()
            .reset_index(name="count")
        )
        if pivot.empty:
            ctx["rows"] = 0
            st.info("No grouped data.")
            return
        table = pivot.pivot_table(
            index="severity", columns="sensor_type", values="count", fill_value=0
        )
        order = [s for s in ["critical", "warning", "info"] if s in table.index]
        table = table.reindex(order)
        ctx["rows"] = len(table)

    st.bar_chart(table, use_container_width=True, height=200)


def _chart_machine_health(df_sensors: pd.DataFrame) -> None:
    st.subheader("🏭 Machine Health Snapshot")

    with st.expander("🔍 Flink SQL", expanded=False):
        st.code(SQL["machine_health"], language="sql")

    if df_sensors.empty:
        st.info("Waiting for sensor data…")
        return

    with _log_query("machine_health") as ctx:
        latest = (
            df_sensors.sort_values("ts", na_position="first")
            .groupby(["machine_id", "sensor_type"])
            .last()
            .reset_index()[["machine_id", "sensor_type", "value"]]
        )

        def _health(row: pd.Series) -> str:
            threshold = THRESHOLDS.get(row["sensor_type"])
            if threshold is None:
                return "normal"
            ratio = row["value"] / threshold
            if ratio >= 0.95:
                return "critical"
            if ratio >= 0.75:
                return "warning"
            return "normal"

        latest["status"] = latest.apply(_health, axis=1)
        latest["pct"]    = latest.apply(
            lambda r: round(r["value"] / THRESHOLDS[r["sensor_type"]] * 100, 1)
            if r["sensor_type"] in THRESHOLDS else None,
            axis=1,
        )
        score_map = {"normal": 1, "warning": 2, "critical": 3}
        latest["score"] = latest["status"].map(score_map)
        ctx["rows"] = len(latest)

    pivot = latest.pivot_table(
        index="machine_id", columns="sensor_type", values="score", fill_value=0
    )
    st.bar_chart(pivot, use_container_width=True, height=200)
    st.caption("Score: 1 = normal · 2 = warning · 3 = critical")

    detail = latest[["machine_id", "sensor_type", "value", "pct", "status"]].copy()
    detail["value"]  = detail["value"].round(2)
    detail["status"] = detail["status"].map(
        {"critical": "🔴 critical", "warning": "🟡 warning", "normal": "🟢 normal"}
    )
    st.dataframe(
        detail.rename(columns={
            "machine_id": "Machine", "sensor_type": "Sensor",
            "value": "Latest value", "pct": "% of threshold", "status": "Status",
        }),
        use_container_width=True, hide_index=True,
    )


# ── Query activity log ────────────────────────────────────────────────────────

def _render_query_log() -> None:
    st.subheader("🗒 Query Activity Log")

    if not _qlog:
        st.info("No queries executed yet — data will appear here once the charts load.")
        return

    log = list(_qlog)

    # ── Summary strip: last-run stats for each query ──────────────────────────
    # Build a dict of the most-recent entry per query key
    seen: dict[str, dict] = {}
    for entry in log:
        if entry["query"] not in seen:
            seen[entry["query"]] = entry

    cols = st.columns(len(seen))
    for col, (qkey, e) in zip(cols, seen.items()):
        status_icon = "✅" if e["status"] == "ok" else "❌"
        col.metric(
            label=f"{status_icon} {e['label']}",
            value=f"{e['duration_ms']} ms",
            delta=f"{e['rows']} rows",
            delta_color="off",
        )

    st.divider()

    # ── Full scrollable log table ─────────────────────────────────────────────
    df_log = pd.DataFrame(log)[["ts", "label", "duration_ms", "rows", "status", "error"]]
    df_log.columns = ["Time", "Query", "Duration (ms)", "Rows", "Status", "Error"]
    df_log["Status"] = df_log["Status"].map({"ok": "✅ ok", "error": "❌ error"})

    st.dataframe(df_log, use_container_width=True, hide_index=True, height=220)

    # ── Expandable SQL viewer for each unique query ───────────────────────────
    st.markdown("**SQL statements executed this session**")
    for qkey, e in seen.items():
        with st.expander(f"`{e['label']}`  —  last ran {e['ts']} · {e['duration_ms']} ms · {e['rows']} rows"):
            st.code(e["sql"], language="sql")


# ── Page layout ───────────────────────────────────────────────────────────────

def render() -> None:
    _fetch()

    df_sensors = _sensors_df()
    df_alerts  = _alerts_df()

    # ── Header ────────────────────────────────────────────────────────────────
    st.title("⚡ Flink Analytics")
    st.caption(
        f"Live Kafka snapshot · {len(_sbuf)} sensor events · {len(_abuf)} alert events · "
        f"refreshes every {REFRESH_S}s · "
        f"{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )

    # ── KPI strip ─────────────────────────────────────────────────────────────
    machines    = df_sensors["machine_id"].nunique()  if not df_sensors.empty else 0
    crit_alerts = (df_alerts["severity"] == "critical").sum() if not df_alerts.empty else 0
    avg_score   = df_alerts["anomaly_score"].mean()           if not df_alerts.empty else 0.0
    total_runs  = len(_qlog)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Sensor events (buffer)", f"{len(_sbuf):,}")
    k2.metric("Machines tracked",        machines)
    k3.metric("🔴 Critical alerts",       int(crit_alerts))
    k4.metric("Queries executed",         total_runs)

    st.divider()

    # ── 2×2 chart grid ────────────────────────────────────────────────────────
    row1_left, row1_right = st.columns(2)
    with row1_left:
        _chart_rolling_avg(df_sensors)
    with row1_right:
        _chart_anomaly_scores(df_alerts)

    st.divider()

    row2_left, row2_right = st.columns(2)
    with row2_left:
        _chart_severity_mix(df_alerts)
    with row2_right:
        _chart_machine_health(df_sensors)

    st.divider()

    # ── Query activity log ────────────────────────────────────────────────────
    _render_query_log()

    st.divider()

    # ── Raw topic browser ─────────────────────────────────────────────────────
    with st.expander("🗄️ Raw topic browser", expanded=False):
        topic_choice = st.radio(
            "Topic", [TOPIC_SENSORS, TOPIC_ALERTS], horizontal=True
        )
        n = st.slider("Show last N events", 10, min(200, BUFFER_SIZE), 50)
        raw_buf = _sbuf if topic_choice == TOPIC_SENSORS else _abuf
        if raw_buf:
            st.dataframe(
                pd.DataFrame(list(raw_buf)[-n:]),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info(f"No data in `{topic_choice}` buffer yet.")

    # ── Auto-refresh ──────────────────────────────────────────────────────────
    time.sleep(REFRESH_S)
    st.rerun()


if __name__ == "__main__":
    render()
