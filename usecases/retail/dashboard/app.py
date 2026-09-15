"""
usecases/retail/dashboard/app.py — Real-Time Retail Analytics Dashboard.

Reads from three Kafka topics:
  retail-orders   → live purchase events
  retail-returns  → return / refund events
  retail-browse   → page views and add-to-cart

Features
--------
  • KPI strip: revenue · orders · returns · return rate · avg basket
  • Live order feed table (colour-coded by status)
  • Top spenders leaderboard
  • Inactive customers alert list
  • High returners alert list
  • Pipeline architecture diagram
  • Inline scheduler (produce events every N seconds)
  • Auto-refreshes every REFRESH_S seconds

Run
---
    KAFKA_ENV=onprem streamlit run usecases/retail/dashboard/app.py
    # Or via the launcher:
    bash usecases/retail/run.sh
"""

import json
import os
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

sys.path.insert(0, ".")
sys.path.insert(0, "usecases/retail")

from auth import kafka_config
from confluent_kafka import Consumer, KafkaError, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from topics import (
    CUSTOMERS, CUSTOMER_MAP, PRODUCTS,
    TOPIC_ORDERS, TOPIC_RETURNS, TOPIC_BROWSE, ALL_TOPICS,
    SEGMENT_COLOUR, STATUS_COLOUR,
    INACTIVE_CUSTOMERS, HIGH_RETURNERS,
)
from producer import produce_batch, _producer as make_producer

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Retail Analytics — Confluent",
    page_icon="🛍️",
    layout="wide",
)

REFRESH_S = int(os.getenv("DASHBOARD_REFRESH_S", "4"))
BUF_SIZE  = 2000

# ── Shared buffers (process-level, survive Streamlit reruns) ──────────────────
@st.cache_resource
def _order_buffer()  -> deque: return deque(maxlen=BUF_SIZE)

@st.cache_resource
def _return_buffer() -> deque: return deque(maxlen=BUF_SIZE)

@st.cache_resource
def _browse_buffer() -> deque: return deque(maxlen=BUF_SIZE)

@st.cache_resource
def _scheduler_state() -> dict:
    return {"running": False, "interval": 3, "thread": None, "total": 0}

# ── Kafka consumers (cached — created once per process) ───────────────────────
def _make_consumer(client_id: str, group_id: str) -> Consumer:
    cfg = kafka_config(client_id=client_id, group_id=group_id)
    cfg["auto.offset.reset"]  = "earliest"
    cfg["enable.auto.commit"] = False
    cfg["session.timeout.ms"] = 10000
    return Consumer(cfg)

@st.cache_resource
def _orders_consumer()  -> Consumer:
    c = _make_consumer("retail-dash-orders", "retail-dash-orders")
    c.subscribe([TOPIC_ORDERS])
    return c

@st.cache_resource
def _returns_consumer() -> Consumer:
    c = _make_consumer("retail-dash-returns", "retail-dash-returns")
    c.subscribe([TOPIC_RETURNS])
    return c

@st.cache_resource
def _browse_consumer()  -> Consumer:
    c = _make_consumer("retail-dash-browse", "retail-dash-browse")
    c.subscribe([TOPIC_BROWSE])
    return c

# ── Topic auto-creation ────────────────────────────────────────────────────────
@st.cache_resource
def _ensure_topics() -> list[str]:
    cfg = kafka_config(client_id="retail-admin")
    cfg.pop("session.timeout.ms", None)
    admin = AdminClient(cfg)
    existing = set(admin.list_topics(timeout=10).topics.keys())
    to_create = [t for t in ALL_TOPICS if t not in existing]
    if not to_create:
        return []
    fs = admin.create_topics([NewTopic(t, num_partitions=3, replication_factor=3) for t in to_create])
    # Wait for each topic creation future to resolve
    for topic, f in fs.items():
        try:
            f.result()
        except Exception:
            pass
    time.sleep(2)   # allow broker metadata to propagate before any produce
    return to_create

# ── Kafka fetch ────────────────────────────────────────────────────────────────
def _fetch() -> None:
    bufs = [(_orders_consumer(),  _order_buffer()),
            (_returns_consumer(), _return_buffer()),
            (_browse_consumer(),  _browse_buffer())]
    for consumer, buf in bufs:
        # Cold start: allow a bit more time; warm: just drain new msgs
        drain_secs = 3.0 if len(buf) == 0 else 1.5
        end_t   = time.time() + drain_secs
        empties = 0
        while time.time() < end_t:
            msg = consumer.poll(0.1)
            if msg is None:
                empties += 1
                if empties >= 5:   # 5 × 0.1s = 0.5s with no data → bail early
                    break
                continue
            empties = 0
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    break         # reached end of partition, stop waiting
                continue
            try:
                buf.append(json.loads(msg.value().decode("utf-8", errors="replace")))
            except Exception:
                pass

# ── Scheduler thread ───────────────────────────────────────────────────────────
@st.cache_resource
def _producer_holder() -> dict:
    """Holds the producer in a dict so it can be replaced without breaking the cache."""
    return {"p": None}

def _cached_producer() -> Producer:
    holder = _producer_holder()
    if holder["p"] is None:
        holder["p"] = make_producer()
    return holder["p"]

def _reset_producer() -> None:
    """Replace the producer — call after topic creation to avoid stale metadata."""
    holder = _producer_holder()
    try:
        if holder["p"]:
            holder["p"].flush(2)
    except Exception:
        pass
    holder["p"] = make_producer()

def _scheduler_loop(state: dict) -> None:
    p = _cached_producer()
    while state["running"]:
        n = produce_batch(p, 5)
        state["total"] += n
        time.sleep(state["interval"])

def _start_scheduler(state: dict) -> None:
    if state["running"]:
        return
    state["running"] = True
    t = threading.Thread(target=_scheduler_loop, args=(state,), daemon=True)
    t.start()
    state["thread"] = t

def _stop_scheduler(state: dict) -> None:
    state["running"] = False

# ── Pipeline diagram ───────────────────────────────────────────────────────────
def _render_flow_diagram() -> None:
    svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 185" width="100%" height="185">
  <defs>
    <marker id="arr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
      <polygon points="0 0,7 3.5,0 7" fill="#64748b"/>
    </marker>
  </defs>
  <rect width="980" height="185" fill="#f8fafc" rx="10"/>

  <!-- Producer -->
  <rect x="10" y="45" width="140" height="100" rx="8" fill="#f0f9ff" stroke="#38bdf8" stroke-width="1.5"/>
  <text x="80" y="68"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#0369a1">🛍️ Event Producer</text>
  <text x="80" y="83"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#0284c7">20 customers</text>
  <text x="80" y="97"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#0284c7">purchases</text>
  <text x="80" y="111" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#0284c7">returns · browse</text>
  <text x="80" y="158" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8"  fill="#94a3b8">producer.py</text>

  <line x1="151" y1="95" x2="183" y2="95" stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>

  <!-- Kafka Topics -->
  <rect x="184" y="25" width="155" height="145" rx="8" fill="#fff7ed" stroke="#fb923c" stroke-width="1.5"/>
  <text x="261" y="48"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#9a3412">🟠 Kafka Topics</text>
  <text x="261" y="65"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#c2410c">retail-orders</text>
  <text x="261" y="81"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#c2410c">retail-returns</text>
  <text x="261" y="97"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#c2410c">retail-browse</text>
  <text x="261" y="113" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#c2410c">3 partitions each</text>
  <text x="261" y="129" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#c2410c">replication=3</text>
  <text x="261" y="158" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8"  fill="#94a3b8">Confluent on-prem VM</text>

  <line x1="340" y1="70"  x2="372" y2="70"  stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="340" y1="95"  x2="372" y2="95"  stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="340" y1="120" x2="372" y2="120" stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>

  <!-- Stream Processing -->
  <rect x="373" y="45" width="155" height="100" rx="8" fill="#f0fdf4" stroke="#86efac" stroke-width="1.5"/>
  <text x="450" y="68"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#166534">⚡ Stream Processing</text>
  <text x="450" y="83"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#15803d">spend aggregation</text>
  <text x="450" y="97"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#15803d">inactivity detection</text>
  <text x="450" y="111" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#15803d">return rate scoring</text>
  <text x="450" y="125" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#15803d">category ranking</text>
  <text x="450" y="158" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8"  fill="#94a3b8">Flink SQL / ksqlDB</text>

  <line x1="529" y1="95" x2="561" y2="95" stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>

  <!-- Dashboard -->
  <rect x="562" y="45" width="155" height="100" rx="8" fill="#f3e8ff" stroke="#a855f7" stroke-width="1.5"/>
  <text x="639" y="68"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#6b21a8">📊 Live Dashboard</text>
  <text x="639" y="83"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#7e22ce">KPI strip</text>
  <text x="639" y="97"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#7e22ce">top spenders</text>
  <text x="639" y="111" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#7e22ce">inactive customers</text>
  <text x="639" y="125" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#7e22ce">high returners</text>
  <text x="639" y="158" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8"  fill="#94a3b8">dashboard/app.py</text>

  <line x1="718" y1="95" x2="750" y2="95" stroke="#64748b" stroke-width="1.5" marker-end="url(#arr)"/>

  <!-- MCP / Alerts -->
  <rect x="751" y="45" width="155" height="100" rx="8" fill="#fee2e2" stroke="#ef4444" stroke-width="1.5"/>
  <text x="828" y="68"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" font-weight="600" fill="#991b1b">🤖 MCP Agent</text>
  <text x="828" y="83"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#dc2626">top shoppers query</text>
  <text x="828" y="97"  text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#dc2626">inactive alerts</text>
  <text x="828" y="111" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#dc2626">return analysis</text>
  <text x="828" y="125" text-anchor="middle" font-family="system-ui,sans-serif" font-size="9"  fill="#dc2626">send reminder</text>
  <text x="828" y="158" text-anchor="middle" font-family="system-ui,sans-serif" font-size="8"  fill="#94a3b8">mcp_server/server.py</text>
</svg>
"""
    st.html(f'<div style="width:100%;height:200px">{svg}</div>')


# ── Analytics helpers ──────────────────────────────────────────────────────────

def _build_stats() -> dict:
    orders  = list(_order_buffer())
    returns = list(_return_buffer())

    completed = [o for o in orders if o.get("status") == "completed"]
    revenue   = sum(float(o.get("total", 0)) for o in completed)
    avg_basket = revenue / len(completed) if completed else 0.0

    return_rate = len(returns) / len(completed) * 100 if completed else 0.0

    spend:  dict[str, float] = defaultdict(float)
    ocount: dict[str, int]   = defaultdict(int)
    for o in completed:
        cid = o.get("customer_id", "")
        spend[cid]  += float(o.get("total", 0))
        ocount[cid] += 1

    top_spenders = sorted(spend.items(), key=lambda x: x[1], reverse=True)[:5]

    # Inactive detection (no order in last 10 min for demo purposes)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    last_order: dict[str, datetime] = {}
    for o in orders:
        cid = o.get("customer_id", "")
        try:
            ts = datetime.fromisoformat(o["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if cid not in last_order or ts > last_order[cid]:
                last_order[cid] = ts
        except Exception:
            pass

    inactive = [
        c for c in CUSTOMERS
        if c["customer_id"] not in last_order
        or last_order[c["customer_id"]] < cutoff
    ]

    # High returners
    rcount: dict[str, int] = defaultdict(int)
    for r in returns:
        rcount[r.get("customer_id", "")] += 1
    high_ret = [
        (cid, rc) for cid, rc in rcount.items()
        if ocount.get(cid, 0) > 0 and rc / ocount[cid] >= 0.4
    ]
    high_ret.sort(key=lambda x: x[1], reverse=True)

    return {
        "orders":       orders,
        "completed":    completed,
        "returns":      returns,
        "revenue":      revenue,
        "avg_basket":   avg_basket,
        "return_rate":  return_rate,
        "top_spenders": top_spenders,
        "inactive":     inactive,
        "high_ret":     high_ret,
        "spend":        spend,
        "ocount":       ocount,
    }


def _recent_orders_df(orders: list[dict]) -> pd.DataFrame:
    rows = []
    for o in sorted(orders, key=lambda x: x.get("ts",""), reverse=True)[:50]:
        seg = o.get("segment","")
        rows.append({
            "Customer":  o.get("customer_name",""),
            "Segment":   seg,
            "Product":   o.get("product_name",""),
            "Category":  o.get("category",""),
            "Qty":       int(o.get("quantity",1)),
            "Total ($)": float(o.get("total",0)),
            "Status":    o.get("status",""),
            "Time":      str(o.get("ts",""))[:16].replace("T"," "),
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── Sidebar ────────────────────────────────────────────────────────────────────
def _sidebar(stats: dict) -> None:
    state = _scheduler_state()
    with st.sidebar:
        st.title("🛍️ Retail Analytics")
        st.caption("Confluent Kafka · real-time retail stream")
        st.divider()

        # Scheduler
        st.subheader("📡 Event Scheduler")
        col1, col2 = st.columns(2)
        if col1.button("▶ Start", use_container_width=True, disabled=state["running"]):
            _start_scheduler(state)
            st.rerun()
        if col2.button("⏹ Stop", use_container_width=True, disabled=not state["running"]):
            _stop_scheduler(state)
            st.rerun()

        state["interval"] = st.slider("Interval (s)", 1, 10, state["interval"])
        if state["running"]:
            st.success(f"🟢 Running — {state['total']} events produced")
        else:
            st.info("⚪ Stopped")

        st.divider()

        # Quick produce
        st.subheader("⚡ Quick Produce")
        if st.button("Produce 50 events now", use_container_width=True):
            p = _cached_producer()
            n = produce_batch(p, 50)
            st.success(f"✓ Produced {n} events")

        st.divider()

        # Stats summary
        st.subheader("📊 Session Stats")
        st.metric("Orders", len(stats["orders"]))
        st.metric("Revenue",  f"${stats['revenue']:,.2f}")
        st.metric("Returns",  len(stats["returns"]))
        st.metric("Inactive", len(stats["inactive"]))


# ── Main render ────────────────────────────────────────────────────────────────
def render() -> None:
    created = _ensure_topics()

    # After topic creation, reset the producer so it picks up the new topic metadata
    if created:
        _reset_producer()

    buf = _order_buffer()
    if len(buf) == 0:
        with st.spinner("Connecting to Kafka and loading retail data…"):
            _fetch()
        # If still empty after fetch, auto-seed 100 events so the page isn't blank
        if len(buf) == 0:
            with st.spinner("Topics empty — seeding initial events…"):
                p = _cached_producer()
                n = produce_batch(p, 100)
                if n > 0:
                    time.sleep(1)   # let broker index the messages before consuming
                _fetch()
    else:
        _fetch()

    stats = _build_stats()

    _sidebar(stats)

    # Header
    st.title("🛍️ Real-Time Retail Analytics")
    st.caption(
        f"Live Kafka streams · {TOPIC_ORDERS} · {TOPIC_RETURNS} · {TOPIC_BROWSE} · "
        f"{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )

    if created:
        st.success(f"✅ Topics created: {', '.join(f'`{t}`' for t in created)}")

    # Pipeline diagram
    with st.expander("🔀 Pipeline Architecture", expanded=False):
        _render_flow_diagram()

    st.divider()

    # ── KPI strip ─────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("💰 Revenue",      f"${stats['revenue']:,.2f}")
    k2.metric("🛒 Orders",       len(stats["completed"]))
    k3.metric("↩️ Returns",      len(stats["returns"]))
    k4.metric("📦 Return Rate",  f"{stats['return_rate']:.1f}%",
              delta=f"{stats['return_rate'] - 15:.1f}% vs 15% target",
              delta_color="inverse")
    k5.metric("🧺 Avg Basket",   f"${stats['avg_basket']:.2f}")

    st.divider()

    # ── Two-column layout ──────────────────────────────────────────────────────
    left, right = st.columns([2, 1])

    with left:
        st.subheader("🧾 Live Order Feed")
        df = _recent_orders_df(stats["orders"])
        if df.empty:
            st.info(
                "No orders yet. Start the scheduler in the sidebar, or run:\n\n"
                "```\nKAFKA_ENV=onprem python3 usecases/retail/producer.py\n```"
            )
        else:
            def _colour_status(val):
                colours = {"completed": "#d1fae5", "pending": "#fef9c3",
                           "cancelled": "#fee2e2", "returned": "#ede9fe"}
                return f"background-color: {colours.get(val, '')}"

            st.dataframe(
                df.style.map(_colour_status, subset=["Status"]),
                width="stretch", hide_index=True, height=340,
            )

    with right:
        st.subheader("🏆 Top Spenders")
        if stats["top_spenders"]:
            rows = []
            for cid, total in stats["top_spenders"]:
                info = CUSTOMER_MAP.get(cid, {})
                rows.append({
                    "Customer": info.get("name", cid),
                    "Segment":  info.get("segment",""),
                    "Spend ($)": round(total, 2),
                    "Orders":   stats["ocount"].get(cid, 0),
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.info("No completed orders yet.")

    st.divider()

    # ── Alert panels ──────────────────────────────────────────────────────────
    al, ar = st.columns(2)

    with al:
        inactive = stats["inactive"]
        st.subheader(f"😴 Inactive Customers ({len(inactive)})")
        st.caption("No orders in the last 10 minutes")
        if inactive:
            rows = [{
                "Customer": c["name"],
                "Segment":  c["segment"],
                "Email":    c["email"],
            } for c in inactive[:10]]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            if len(inactive) > 10:
                st.caption(f"… and {len(inactive)-10} more")
        else:
            st.success("All customers active!")

    with ar:
        high_ret = stats["high_ret"]
        st.subheader(f"↩️ High Returners ({len(high_ret)})")
        st.caption("Return rate ≥ 40% of completed orders")
        if high_ret:
            rows = []
            for cid, rc in high_ret[:10]:
                info  = CUSTOMER_MAP.get(cid, {})
                oc    = stats["ocount"].get(cid, 0)
                rate  = rc / oc * 100 if oc else 0
                rows.append({
                    "Customer":    info.get("name", cid),
                    "Orders":      oc,
                    "Returns":     rc,
                    "Return Rate": f"{rate:.0f}%",
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.success("No high returners detected!")

    # ── Auto-refresh ──────────────────────────────────────────────────────────
    time.sleep(REFRESH_S)
    st.rerun()


render()
