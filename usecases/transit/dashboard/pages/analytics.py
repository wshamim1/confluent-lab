"""
transit/dashboard/pages/analytics.py — Delay Analytics for the Transit Dashboard.

Four live charts driven by the transit-events buffer, each paired with the
Flink SQL that would run the same transform at scale:

  ┌────────────────────────────┬────────────────────────────┐
  │  Delay distribution (hist) │  Carrier on-time ranking   │
  ├────────────────────────────┼────────────────────────────┤
  │  Status mix by mode        │  Hourly delay heatmap      │
  └────────────────────────────┴────────────────────────────┘

Plus a live Query Activity Log (timing, row count, SQL) below the charts.

Run alongside the main dashboard:
    KAFKA_ENV=onprem streamlit run transit/dashboard/app.py
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

sys.path.insert(0, "usecases/transit")
from topics import TOPIC_EVENTS

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Transit Analytics — Confluent",
    page_icon="📊",
    layout="wide",
)

# ── Constants ─────────────────────────────────────────────────────────────────
REFRESH_S   = int(os.getenv("TRANSIT_REFRESH_S", "4"))
MAX_LOG     = 50

# ── SQL definitions ────────────────────────────────────────────────────────────
SQL = {
    "delay_dist": """\
SELECT
    CASE
        WHEN delay_minutes = 0          THEN 'on time'
        WHEN delay_minutes BETWEEN 1 AND 15  THEN '1–15 min'
        WHEN delay_minutes BETWEEN 16 AND 30 THEN '16–30 min'
        WHEN delay_minutes BETWEEN 31 AND 60 THEN '31–60 min'
        ELSE                                      '> 60 min'
    END AS delay_bucket,
    COUNT(*) AS trip_count
FROM transit_events_view
WHERE status IN ('delayed', 'on_time')
GROUP BY
    CASE
        WHEN delay_minutes = 0          THEN 'on time'
        WHEN delay_minutes BETWEEN 1 AND 15  THEN '1–15 min'
        WHEN delay_minutes BETWEEN 16 AND 30 THEN '16–30 min'
        WHEN delay_minutes BETWEEN 31 AND 60 THEN '31–60 min'
        ELSE                                      '> 60 min'
    END
ORDER BY trip_count DESC;""",

    "carrier_ranking": """\
SELECT
    carrier,
    COUNT(*)                                          AS total_trips,
    SUM(CASE WHEN status = 'on_time'   THEN 1 ELSE 0 END) AS on_time,
    SUM(CASE WHEN status = 'delayed'   THEN 1 ELSE 0 END) AS delayed,
    SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
    ROUND(
        SUM(CASE WHEN status = 'on_time' THEN 1.0 ELSE 0 END)
        / COUNT(*) * 100, 1
    )                                                 AS on_time_pct,
    AVG(delay_minutes)                                AS avg_delay_min
FROM transit_events_view
GROUP BY carrier
ORDER BY on_time_pct DESC;""",

    "status_by_mode": """\
SELECT
    mode,
    status,
    COUNT(*) AS trip_count
FROM transit_events_view
GROUP BY mode, status
ORDER BY mode, trip_count DESC;""",

    "hourly_heatmap": """\
SELECT
    HOUR(TO_TIMESTAMP(scheduled_dep)) AS departure_hour,
    mode,
    AVG(delay_minutes)                AS avg_delay_min,
    COUNT(*)                          AS trip_count
FROM transit_events_view
WHERE status = 'delayed'
GROUP BY
    HOUR(TO_TIMESTAMP(scheduled_dep)),
    mode
ORDER BY departure_hour, mode;""",
}

QUERY_LABELS = {
    "delay_dist":      "Delay Distribution",
    "carrier_ranking": "Carrier On-Time Ranking",
    "status_by_mode":  "Status Mix by Mode",
    "hourly_heatmap":  "Hourly Delay Heatmap",
}

# ── Shared process-level event buffer (cache_resource survives page switches) ──
# Both app.py and analytics.py write into the same deque so the analytics page
# sees every event the main dashboard has already consumed.

@st.cache_resource
def _shared_event_buffer() -> deque:
    return deque(maxlen=500)


# ── Session state (page-local only) ───────────────────────────────────────────
if "ta_query_log" not in st.session_state:
    st.session_state.ta_query_log = deque(maxlen=MAX_LOG)

_qlog = st.session_state.ta_query_log


# ── Query logger ──────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _log_query(key: str):
    t0  = time.perf_counter()
    ctx: dict = {"rows": 0, "status": "ok", "error": ""}
    try:
        yield ctx
    except Exception as exc:
        ctx["status"] = "error"
        ctx["error"]  = str(exc)
        raise
    finally:
        ms = round((time.perf_counter() - t0) * 1000, 1)
        _qlog.appendleft({
            "query":       key,
            "label":       QUERY_LABELS.get(key, key),
            "sql":         SQL.get(key, ""),
            "duration_ms": ms,
            "rows":        ctx["rows"],
            "status":      ctx["status"],
            "error":       ctx["error"],
            "ts":          datetime.now(timezone.utc).strftime("%H:%M:%S"),
        })


# ── Kafka helpers ─────────────────────────────────────────────────────────────

@st.cache_resource
def _get_consumer() -> Consumer:
    cfg = kafka_config(
        client_id=f"transit-analytics-{uuid.uuid4().hex[:6]}",
        group_id=f"transit-analytics-{uuid.uuid4().hex[:8]}",
    )
    # earliest so the analytics page catches events produced before it opened
    cfg["auto.offset.reset"]  = "earliest"
    cfg["enable.auto.commit"] = False
    cfg["session.timeout.ms"] = 10000
    c = Consumer(cfg)
    c.subscribe([TOPIC_EVENTS])
    return c


def _fetch() -> None:
    buf   = _shared_event_buffer()
    c     = _get_consumer()
    end_t = time.time() + 1.5
    while time.time() < end_t:
        msg = c.poll(0.05)
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


def _events_df() -> pd.DataFrame:
    buf = _shared_event_buffer()
    if not buf:
        return pd.DataFrame()
    df = pd.DataFrame(list(buf))
    for col in ("trip_id", "route_id", "mode", "carrier", "origin",
                "destination", "scheduled_dep", "status", "delay_minutes"):
        if col not in df.columns:
            df[col] = None
    df["delay_minutes"] = pd.to_numeric(df["delay_minutes"], errors="coerce").fillna(0)
    try:
        df["dep_hour"] = pd.to_datetime(df["scheduled_dep"], utc=True, errors="coerce").dt.hour
    except Exception:
        df["dep_hour"] = None
    return df


# ── Chart renderers ───────────────────────────────────────────────────────────

def _chart_delay_dist(df: pd.DataFrame) -> None:
    st.subheader("📊 Delay Distribution")
    with st.expander("🔍 Flink SQL", expanded=False):
        st.code(SQL["delay_dist"], language="sql")

    if df.empty:
        st.info("No event data yet — start the scheduler or run producer.py.")
        return

    with _log_query("delay_dist") as ctx:
        bins   = [-1, 0, 15, 30, 60, 9999]
        labels = ["on time", "1–15 min", "16–30 min", "31–60 min", "> 60 min"]
        df2    = df.copy()
        df2["bucket"] = pd.cut(df2["delay_minutes"], bins=bins, labels=labels)
        counts = (
            df2["bucket"].value_counts()
            .reindex(labels, fill_value=0)
            .reset_index()
        )
        counts.columns = ["Delay bucket", "Trips"]
        ctx["rows"] = len(counts)

    st.bar_chart(counts.set_index("Delay bucket"), width="stretch", height=220)


def _chart_carrier_ranking(df: pd.DataFrame) -> None:
    st.subheader("🏆 Carrier On-Time Ranking")
    with st.expander("🔍 Flink SQL", expanded=False):
        st.code(SQL["carrier_ranking"], language="sql")

    if df.empty:
        st.info("No event data yet.")
        return

    with _log_query("carrier_ranking") as ctx:
        grp = df.groupby("carrier")
        total    = grp["status"].count()
        on_time  = grp["status"].apply(lambda s: (s == "on_time").sum())
        delayed  = grp["status"].apply(lambda s: (s == "delayed").sum())
        cancelled= grp["status"].apply(lambda s: (s == "cancelled").sum())
        avg_d    = df[df["status"] == "delayed"].groupby("carrier")["delay_minutes"].mean().round(1)

        ranking = pd.DataFrame({
            "Total":      total,
            "On Time":    on_time,
            "Delayed":    delayed,
            "Cancelled":  cancelled,
            "On-Time %":  (on_time / total * 100).round(1),
            "Avg Delay":  avg_d,
        }).sort_values("On-Time %", ascending=False).reset_index()
        ctx["rows"] = len(ranking)

    st.bar_chart(
        ranking.set_index("carrier")[["On-Time %"]],
        width="stretch", height=220,
    )
    st.dataframe(ranking, width="stretch", hide_index=True)


def _chart_status_by_mode(df: pd.DataFrame) -> None:
    st.subheader("✈️🚆🚌 Status Mix by Mode")
    with st.expander("🔍 Flink SQL", expanded=False):
        st.code(SQL["status_by_mode"], language="sql")

    if df.empty:
        st.info("No event data yet.")
        return

    with _log_query("status_by_mode") as ctx:
        pivot = (
            df.groupby(["mode", "status"])
            .size()
            .reset_index(name="count")
            .pivot_table(index="mode", columns="status", values="count", fill_value=0)
        )
        for col in ["on_time", "delayed", "cancelled"]:
            if col not in pivot.columns:
                pivot[col] = 0
        pivot = pivot[["on_time", "delayed", "cancelled"]]
        ctx["rows"] = len(pivot)

    st.bar_chart(pivot, width="stretch", height=220)
    st.caption("Columns: on_time · delayed · cancelled")


def _chart_hourly_heatmap(df: pd.DataFrame) -> None:
    st.subheader("🕐 Avg Delay by Departure Hour")
    with st.expander("🔍 Flink SQL", expanded=False):
        st.code(SQL["hourly_heatmap"], language="sql")

    if df.empty or df["dep_hour"].isna().all():
        st.info("No event data yet.")
        return

    with _log_query("hourly_heatmap") as ctx:
        delayed = df[df["status"] == "delayed"].copy()
        if delayed.empty:
            ctx["rows"] = 0
            st.info("No delayed trips yet — inject a delay wave to see this chart.")
            return
        heat = (
            delayed.groupby(["dep_hour", "mode"])["delay_minutes"]
            .mean()
            .reset_index()
            .pivot_table(index="dep_hour", columns="mode", values="delay_minutes", fill_value=0)
            .round(1)
        )
        ctx["rows"] = len(heat)

    st.line_chart(heat, width="stretch", height=220)
    st.caption("Average delay in minutes per departure hour, split by mode")


# ── Query activity log ────────────────────────────────────────────────────────

def _render_query_log() -> None:
    st.subheader("🗒 Query Activity Log")

    if not _qlog:
        st.info("No queries run yet — charts will populate on first data load.")
        return

    log  = list(_qlog)
    seen: dict[str, dict] = {}
    for e in log:
        if e["query"] not in seen:
            seen[e["query"]] = e

    cols = st.columns(len(seen))
    for col, (_, e) in zip(cols, seen.items()):
        icon = "✅" if e["status"] == "ok" else "❌"
        col.metric(
            label=f"{icon} {e['label']}",
            value=f"{e['duration_ms']} ms",
            delta=f"{e['rows']} rows",
            delta_color="off",
        )

    st.divider()

    df_log = pd.DataFrame(log)[["ts", "label", "duration_ms", "rows", "status", "error"]]
    df_log.columns = ["Time", "Query", "Duration (ms)", "Rows", "Status", "Error"]
    df_log["Status"] = df_log["Status"].map({"ok": "✅ ok", "error": "❌ error"})
    st.dataframe(df_log, width="stretch", hide_index=True, height=200)

    st.markdown("**SQL statements executed this session**")
    for _, e in seen.items():
        with st.expander(f"`{e['label']}` — {e['ts']} · {e['duration_ms']} ms · {e['rows']} rows"):
            st.code(e["sql"], language="sql")


# ── Page layout ───────────────────────────────────────────────────────────────

def render() -> None:
    _fetch()
    df = _events_df()

    st.title("📊 Transit Delay Analytics")
    st.caption(
        f"Live snapshot · {len(_shared_event_buffer())} events buffered · "
        f"refreshes every {REFRESH_S}s · "
        f"{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )

    # KPI strip
    total     = len(df)
    on_time   = int((df["status"] == "on_time").sum())   if not df.empty else 0
    delayed   = int((df["status"] == "delayed").sum())   if not df.empty else 0
    cancelled = int((df["status"] == "cancelled").sum()) if not df.empty else 0
    avg_d     = df.loc[df["status"] == "delayed", "delay_minutes"].mean() if not df.empty else 0.0
    queries   = len(_qlog)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Events (buffer)",   f"{total:,}")
    k2.metric("🟢 On Time",         on_time)
    k3.metric("🟡 Delayed",         delayed)
    k4.metric("🔴 Cancelled",       cancelled)
    k5.metric("Queries run",        queries)

    st.divider()

    row1_l, row1_r = st.columns(2)
    with row1_l:
        _chart_delay_dist(df)
    with row1_r:
        _chart_carrier_ranking(df)

    st.divider()

    row2_l, row2_r = st.columns(2)
    with row2_l:
        _chart_status_by_mode(df)
    with row2_r:
        _chart_hourly_heatmap(df)

    st.divider()
    _render_query_log()

    st.divider()
    with st.expander("🗄️ Raw event browser", expanded=False):
        n = st.slider("Show last N events", 10, 300, 50)
        if not df.empty:
            st.dataframe(df.tail(n), width="stretch", hide_index=True)
        else:
            st.info("No events yet.")

    time.sleep(REFRESH_S)
    st.rerun()


if __name__ == "__main__":
    render()
