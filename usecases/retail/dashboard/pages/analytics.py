"""
usecases/retail/dashboard/pages/analytics.py — Retail Flink SQL Analytics.

Four live charts:
  1. Revenue by customer (bar) — top 15 spenders
  2. Return rate by customer (bar) — highest returners
  3. Revenue by category (pie)
  4. Orders over time (line) — 5-min tumbling window

Plus collapsible Flink SQL panels and a query activity log.
"""

import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, ".")
sys.path.insert(0, "usecases/retail")

from topics import CUSTOMER_MAP, TOPIC_ORDERS, TOPIC_RETURNS, FLINK_ORDERS, FLINK_RETURNS

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Retail Analytics — Flink SQL",
    page_icon="📊",
    layout="wide",
)

# ── Shared buffer access ───────────────────────────────────────────────────────
# Import cache_resource functions from the main app so we share the same buffers
sys.path.insert(0, "usecases/retail/dashboard")
from app import _order_buffer, _return_buffer, _fetch

# ── Query log ─────────────────────────────────────────────────────────────────
@st.cache_resource
def _query_log() -> list: return []


def _log(query_name: str, rows: int, ms: float) -> None:
    _query_log().append({
        "time":  datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "query": query_name,
        "rows":  rows,
        "ms":    round(ms, 1),
    })
    if len(_query_log()) > 50:
        _query_log().pop(0)


# ── Analytics builders ─────────────────────────────────────────────────────────

def _revenue_by_customer(orders: list[dict]) -> pd.DataFrame:
    spend: dict[str, float] = defaultdict(float)
    for o in orders:
        if o.get("status") == "completed":
            cid = o.get("customer_id","")
            spend[cid] += float(o.get("total", 0))
    rows = [
        {"Customer": CUSTOMER_MAP.get(cid,{}).get("name", cid),
         "Segment":  CUSTOMER_MAP.get(cid,{}).get("segment","regular"),
         "Revenue":  round(v,2)}
        for cid, v in sorted(spend.items(), key=lambda x: x[1], reverse=True)[:15]
    ]
    return pd.DataFrame(rows)


def _return_rate_by_customer(orders: list[dict], returns: list[dict]) -> pd.DataFrame:
    ocount: dict[str, int] = defaultdict(int)
    rcount: dict[str, int] = defaultdict(int)
    for o in orders:
        if o.get("status") == "completed":
            ocount[o.get("customer_id","")] += 1
    for r in returns:
        rcount[r.get("customer_id","")] += 1

    rows = []
    for cid, rc in sorted(rcount.items(), key=lambda x: x[1], reverse=True):
        oc = ocount.get(cid, 0)
        if oc == 0:
            continue
        rows.append({
            "Customer":    CUSTOMER_MAP.get(cid,{}).get("name", cid),
            "Orders":      oc,
            "Returns":     rc,
            "Return Rate": round(rc / oc * 100, 1),
        })
    return pd.DataFrame(rows[:15]) if rows else pd.DataFrame()


def _revenue_by_category(orders: list[dict]) -> pd.DataFrame:
    spend: dict[str, float] = defaultdict(float)
    for o in orders:
        if o.get("status") == "completed":
            spend[o.get("category","Unknown")] += float(o.get("total", 0))
    return pd.DataFrame([
        {"Category": k, "Revenue": round(v,2)}
        for k, v in sorted(spend.items(), key=lambda x: x[1], reverse=True)
    ])


def _orders_over_time(orders: list[dict], window_min: int = 5) -> pd.DataFrame:
    buckets: dict[str, int]   = defaultdict(int)
    revenue: dict[str, float] = defaultdict(float)
    for o in orders:
        if o.get("status") == "completed":
            try:
                ts = datetime.fromisoformat(o["ts"])
                # truncate to window_min-minute bucket
                mins = (ts.minute // window_min) * window_min
                bucket = ts.replace(minute=mins, second=0, microsecond=0).strftime("%H:%M")
                buckets[bucket] += 1
                revenue[bucket] += float(o.get("total", 0))
            except Exception:
                pass
    rows = [{"Time": k, "Orders": buckets[k], "Revenue": round(revenue[k],2)}
            for k in sorted(buckets)]
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── Flink SQL panels ───────────────────────────────────────────────────────────
FLINK_QUERIES = {
    "Revenue by Customer": f"""-- Tumbling 10-minute window: revenue per customer
SELECT
  customer_id,
  customer_name,
  segment,
  SUM(total)      AS total_revenue,
  COUNT(*)        AS order_count,
  AVG(total)      AS avg_basket
FROM TABLE(
  TUMBLE(TABLE {FLINK_ORDERS}, DESCRIPTOR(event_time), INTERVAL '10' MINUTES)
)
WHERE status = 'completed'
GROUP BY customer_id, customer_name, segment,
         window_start, window_end
ORDER BY total_revenue DESC;""",

    "High Returners (Flink)": f"""-- Customers whose return rate exceeds 30%
SELECT
  o.customer_id,
  o.customer_name,
  COUNT(DISTINCT o.event_id)  AS orders,
  COUNT(DISTINCT r.event_id)  AS returns,
  COUNT(DISTINCT r.event_id) * 100.0
    / NULLIF(COUNT(DISTINCT o.event_id), 0) AS return_rate_pct
FROM {FLINK_ORDERS}  AS o
LEFT JOIN {FLINK_RETURNS} AS r ON o.customer_id = r.customer_id
GROUP BY o.customer_id, o.customer_name
HAVING return_rate_pct >= 30
ORDER BY return_rate_pct DESC;""",

    "Category Revenue": f"""-- Total revenue and items sold by product category
SELECT
  category,
  SUM(total)    AS total_revenue,
  SUM(quantity) AS items_sold,
  COUNT(*)      AS order_count
FROM {FLINK_ORDERS}
WHERE status = 'completed'
GROUP BY category
ORDER BY total_revenue DESC;""",

    "Inactive Customers (7-day)": f"""-- Customers with no completed order in the last 7 days
SELECT
  c.customer_id,
  c.name,
  c.segment,
  MAX(o.event_time) AS last_order_ts,
  CURRENT_TIMESTAMP - MAX(o.event_time) AS days_since_order
FROM customers AS c
LEFT JOIN {FLINK_ORDERS} AS o
  ON c.customer_id = o.customer_id
  AND o.status = 'completed'
  AND o.event_time >= CURRENT_TIMESTAMP - INTERVAL '7' DAY
GROUP BY c.customer_id, c.name, c.segment
HAVING MAX(o.event_time) IS NULL
    OR MAX(o.event_time) < CURRENT_TIMESTAMP - INTERVAL '7' DAY
ORDER BY days_since_order DESC;""",
}

# ── Page ───────────────────────────────────────────────────────────────────────

st.title("📊 Retail Analytics — Flink SQL")
st.caption("Aggregations over `retail-orders` and `retail-returns` Kafka topics")

# Fetch latest data
_fetch()
orders  = list(_order_buffer())
returns = list(_return_buffer())

if not orders:
    st.warning("No order data yet. Start the scheduler on the main dashboard or run `producer.py`.")
    st.stop()

# ── Chart 1 + Chart 2 ─────────────────────────────────────────────────────────
c1, c2 = st.columns(2)

with c1:
    with st.expander("🔍 Flink SQL — Revenue by Customer", expanded=False):
        st.code(FLINK_QUERIES["Revenue by Customer"], language="sql")

    t0 = time.time()
    df_rev = _revenue_by_customer(orders)
    ms = (time.time() - t0) * 1000
    _log("Revenue by Customer", len(df_rev), ms)

    if not df_rev.empty:
        SEG_COLOURS = {"vip": "#7c3aed", "premium": "#2563eb", "regular": "#64748b"}
        fig = px.bar(
            df_rev, x="Revenue", y="Customer", orientation="h",
            color="Segment", color_discrete_map=SEG_COLOURS,
            title="💰 Revenue by Customer (top 15)",
            labels={"Revenue": "Revenue ($)"},
        )
        fig.update_layout(height=380, margin=dict(l=0,r=0,t=35,b=0),
                          yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No completed orders yet.")

with c2:
    with st.expander("🔍 Flink SQL — High Returners", expanded=False):
        st.code(FLINK_QUERIES["High Returners (Flink)"], language="sql")

    t0 = time.time()
    df_ret = _return_rate_by_customer(orders, returns)
    ms = (time.time() - t0) * 1000
    _log("Return Rate by Customer", len(df_ret), ms)

    if not df_ret.empty:
        fig = px.bar(
            df_ret, x="Return Rate", y="Customer", orientation="h",
            color="Return Rate",
            color_continuous_scale=["#16a34a","#ca8a04","#dc2626"],
            range_color=[0, 100],
            title="↩️ Return Rate by Customer (%)",
        )
        fig.update_layout(height=380, margin=dict(l=0,r=0,t=35,b=0),
                          yaxis={"categoryorder": "total ascending"},
                          coloraxis_showscale=False)
        fig.add_vline(x=30, line_dash="dash", line_color="#ef4444",
                      annotation_text="30% threshold")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No return data yet.")

st.divider()

# ── Chart 3 + Chart 4 ─────────────────────────────────────────────────────────
c3, c4 = st.columns(2)

with c3:
    with st.expander("🔍 Flink SQL — Category Revenue", expanded=False):
        st.code(FLINK_QUERIES["Category Revenue"], language="sql")

    t0 = time.time()
    df_cat = _revenue_by_category(orders)
    ms = (time.time() - t0) * 1000
    _log("Category Revenue", len(df_cat), ms)

    if not df_cat.empty:
        fig = px.pie(
            df_cat, values="Revenue", names="Category",
            title="📦 Revenue by Category",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.update_layout(height=380, margin=dict(l=0,r=0,t=35,b=0))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No category data yet.")

with c4:
    with st.expander("🔍 Flink SQL — Inactive Customers", expanded=False):
        st.code(FLINK_QUERIES["Inactive Customers (7-day)"], language="sql")

    t0 = time.time()
    df_time = _orders_over_time(orders, window_min=5)
    ms = (time.time() - t0) * 1000
    _log("Orders Over Time", len(df_time), ms)

    if not df_time.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_time["Time"], y=df_time["Orders"],
            fill="tozeroy", mode="lines+markers",
            line={"color": "#3b82f6", "width": 2},
            name="Orders",
        ))
        fig.update_layout(
            title="🕐 Orders Over Time (5-min buckets)",
            xaxis_title="Time (UTC)", yaxis_title="Order Count",
            height=380, margin=dict(l=0,r=0,t=35,b=0),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Not enough time-series data yet.")

st.divider()

# ── Query activity log ─────────────────────────────────────────────────────────
with st.expander("📋 Query Activity Log", expanded=False):
    log = _query_log()
    if log:
        st.dataframe(
            pd.DataFrame(list(reversed(log))),
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("No queries run yet.")
