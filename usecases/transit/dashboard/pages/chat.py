"""
usecases/transit/dashboard/pages/chat.py — Transit MCP Agent Chat.

Lets you query live transit data via natural language. Intent keywords
route to the correct MCP tool function, results are formatted inline.

Recognised intents
------------------
  "events" / "latest" / "feed"          → transit_read_events
  "route" / "AA-" / "UA-" / "NJ-" …    → transit_get_route_status
  "delayed" / "delays" / "late"          → transit_get_delayed_trips
  "inject" / "simulate" / "force delay"  → transit_inject_delay
  "carrier" / "airline" / "ranking"      → transit_get_carrier_stats
  "trip" / "trip id" / "detail"          → transit_get_trip_detail

Run alongside the main dashboard:
    KAFKA_ENV=onprem streamlit run usecases/transit/dashboard/app.py
"""

import json
import re

import pandas as pd
import sys
from datetime import datetime, timezone

import streamlit as st

sys.path.insert(0, ".")
sys.path.insert(0, "usecases/transit/mcp_server")
sys.path.insert(0, "usecases/transit")

from server import (
    tool_transit_read_events,
    tool_transit_get_route_status,
    tool_transit_get_delayed_trips,
    tool_transit_inject_delay,
    tool_transit_get_carrier_stats,
    tool_transit_get_trip_detail,
)
from producer import ROUTES

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Transit Agent Chat — Confluent",
    page_icon="🤖",
    layout="wide",
)

# ── Session state ─────────────────────────────────────────────────────────────
if "tr_messages" not in st.session_state:
    route_list = ", ".join(r["route_id"] for r in ROUTES[:6]) + " …"
    st.session_state.tr_messages = [
        {
            "role": "assistant",
            "content": (
                "👋 Hi! I'm the Transit Agent — ask me about live flight, train and bus data.\n\n"
                "**What I can do:**\n"
                "- 📡 *Show latest transit events from Kafka*\n"
                f"- 🛫 *Get status for a route* (e.g. AA-101, UA-301, NJ-101)\n"
                "- 🟡 *List all delayed trips* (optionally by mode: flight/train/bus)\n"
                "- 🏆 *Rank carriers by on-time performance*\n"
                "- 🚨 *Inject a delay wave for testing*\n"
                "- 🔍 *Look up a specific trip ID*\n\n"
                f"Available routes: `{route_list}`"
            ),
        }
    ]

# ── Known route IDs ───────────────────────────────────────────────────────────
ROUTE_IDS = [r["route_id"] for r in ROUTES]
MODES     = ["flight", "train", "bus"]


# ── Intent helpers ────────────────────────────────────────────────────────────

def _extract_route(text: str) -> str:
    m = re.search(r'\b([A-Z]{2,4}-\d{1,3}[A-Z]?)\b', text.upper())
    return m.group(1) if m else ""

def _extract_mode(text: str) -> str:
    for mode in MODES:
        if mode in text.lower():
            return mode
    return ""

def _extract_count(text: str) -> int:
    m = re.search(r'\b(\d+)\b', text)
    return min(int(m.group(1)), 30) if m else 10

def _extract_trip_id(text: str) -> str:
    # trip ids look like: AA-101-20260912105300-427
    m = re.search(r'([A-Z]{2,6}-\d{1,3}-\d{14}-\d{3})', text.upper())
    return m.group(1) if m else ""


# ── Tool dispatch ─────────────────────────────────────────────────────────────

def _call_tool(user_input: str) -> tuple[str, str]:
    text = user_input.lower()

    # Trip detail
    trip_id = _extract_trip_id(user_input)
    if trip_id or any(w in text for w in ["trip id", "trip detail", "lookup trip", "find trip"]):
        if not trip_id:
            return "error", "Please provide a trip ID (e.g. AA-101-20260912105300-427)."
        return "transit_get_trip_detail", tool_transit_get_trip_detail({"trip_id": trip_id})

    # Inject delay
    if any(w in text for w in ["inject", "simulate", "force delay", "trigger delay", "produce delay"]):
        route = _extract_route(user_input) or "AA-101"
        count = _extract_count(text)
        return "transit_inject_delay", tool_transit_inject_delay({"route_id": route, "count": count})

    # Route status — explicit route id or "route XX-NNN" pattern
    route = _extract_route(user_input)
    if route or any(w in text for w in ["route status", "how is route", "status of"]):
        if not route:
            return "error", f"Please specify a route ID (e.g. AA-101). Available: {', '.join(ROUTE_IDS[:6])} …"
        return "transit_get_route_status", tool_transit_get_route_status({"route_id": route})

    # Carrier stats
    if any(w in text for w in ["carrier", "airline", "ranking", "best carrier",
                                "worst carrier", "on-time", "performance"]):
        return "transit_get_carrier_stats", tool_transit_get_carrier_stats({})

    # Delayed trips
    if any(w in text for w in ["delayed", "delays", "late", "behind schedule",
                                "not on time", "which trips"]):
        mode = _extract_mode(text)
        return "transit_get_delayed_trips", tool_transit_get_delayed_trips({"mode": mode, "limit": 20})

    # Latest events (default)
    return "transit_read_events", tool_transit_read_events({"limit": 15})


# ── Response renderers (write widgets directly into the current st context) ───

_STATUS_ICON = {"on_time": "🟢", "delayed": "🟡", "cancelled": "🔴"}
_MODE_ICON   = {"flight": "✈️", "train": "🚆", "bus": "🚌"}

def _render_result(tool: str, result_str: str) -> None:
    """Render rich widgets for a tool result. Call inside an st.chat_message block."""
    if tool == "error":
        st.warning(result_str)
        return
    try:
        data = json.loads(result_str)
    except Exception:
        st.markdown(result_str)
        return

    # ── Latest events ─────────────────────────────────────────────────────────
    if tool == "transit_read_events":
        events = data.get("events", [])
        if not events:
            st.info("📡 No events yet. Start the scheduler or run `producer.py`.")
            return
        st.markdown(f"📡 **{len(events)} latest events** from `transit-events`")
        rows = [{
            "Mode":    _MODE_ICON.get(e.get("mode",""), "") + " " + e.get("mode",""),
            "Route":   e.get("route_id",""),
            "From":    e.get("origin",""),
            "To":      e.get("destination",""),
            "Status":  _STATUS_ICON.get(e.get("status",""),"⚪") + " " + e.get("status","").replace("_"," "),
            "Delay":   int(e.get("delay_minutes") or 0),
            "Gate":    e.get("gate") or e.get("platform") or "—",
            "Updated": str(e.get("updated_at",""))[:16].replace("T"," "),
        } for e in events]
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        return

    # ── Route status ──────────────────────────────────────────────────────────
    if tool == "transit_get_route_status":
        if "message" in data:
            st.info(f"🔍 Route `{data.get('route_id')}`: {data['message']}")
            return
        mode = _MODE_ICON.get(data.get("mode",""), "") + " " + data.get("mode","")
        st.markdown(f"### ✈️ Route `{data['route_id']}` — {data.get('carrier','')} · {mode}")
        st.caption(f"📍 {data.get('origin','')} → {data.get('destination','')}")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Trips",  data.get("total_trips", 0))
        c2.metric("🟢 On Time",   f"{data.get('on_time',0)} ({data.get('on_time_pct',0)}%)")
        c3.metric("🟡 Delayed",   data.get("delayed", 0))
        c4.metric("🔴 Cancelled", data.get("cancelled", 0))
        c5.metric("Avg Delay",    f"{data.get('avg_delay_min',0)} min")
        trips = data.get("latest_trips", [])
        if trips:
            st.markdown("**Recent trips:**")
            rows = [{
                "Status":  _STATUS_ICON.get(t.get("status",""),"⚪") + " " + t.get("status","").replace("_"," "),
                "Delay":   int(t.get("delay_minutes") or 0),
                "Gate":    t.get("gate") or t.get("platform") or "—",
                "Updated": str(t.get("updated_at",""))[:16].replace("T"," "),
            } for t in trips]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        return

    # ── Delayed trips ─────────────────────────────────────────────────────────
    if tool == "transit_get_delayed_trips":
        trips = data.get("trips", [])
        mode  = data.get("mode_filter", "all")
        if not trips:
            st.success(f"✅ No delayed trips (mode: {mode}).")
            return
        st.markdown(f"🟡 **{data.get('delayed_count',0)} delayed trip(s)** — mode: `{mode}`")
        rows = [{
            "Mode":    _MODE_ICON.get(t.get("mode",""), "") + " " + t.get("mode",""),
            "Route":   t.get("route_id",""),
            "Carrier": t.get("carrier",""),
            "From":    t.get("origin",""),
            "To":      t.get("destination",""),
            "Delay (min)": int(t.get("delay_minutes") or 0),
            "Gate":    t.get("gate") or t.get("platform") or "—",
        } for t in trips]
        df = pd.DataFrame(rows).sort_values("Delay (min)", ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
        return

    # ── Inject delay ──────────────────────────────────────────────────────────
    if tool == "transit_inject_delay":
        if "error" in data:
            st.error(f"❌ Inject failed: {data['error']}")
            return
        st.success(
            f"🚨 **Delay wave injected** — route `{data.get('route_id')}` "
            f"({data.get('carrier','')})"
        )
        c1, c2 = st.columns(2)
        c1.metric("Events Produced", data.get("events_produced", 0))
        c2.metric("At", str(data.get("timestamp",""))[:19].replace("T"," ") + " UTC")
        return

    # ── Carrier stats ─────────────────────────────────────────────────────────
    if tool == "transit_get_carrier_stats":
        carriers = data.get("carriers", [])
        if not carriers:
            st.info("📊 No carrier data yet — start the scheduler or run `producer.py`.")
            return
        st.markdown(f"🏆 **Carrier On-Time Ranking** — {data.get('total_trips',0)} total trips")
        rows = [{
            "Carrier":       c["carrier"],
            "On-Time %":     c["on_time_pct"],
            "On Time":       c["on_time"],
            "Delayed":       c["delayed"],
            "Cancelled":     c["cancelled"],
            "Avg Delay (min)": c["avg_delay_min"],
        } for c in carriers]
        df = pd.DataFrame(rows)
        st.dataframe(
            df.style.background_gradient(subset=["On-Time %"], cmap="RdYlGn", vmin=0, vmax=100),
            use_container_width=True, hide_index=True,
        )
        return

    # ── Trip detail ───────────────────────────────────────────────────────────
    if tool == "transit_get_trip_detail":
        if "message" in data:
            st.info(f"🔍 Trip `{data.get('trip_id')}`: {data['message']}")
            return
        t = data.get("latest", {})
        st.markdown(f"### 🔍 Trip `{data.get('trip_id')}`")
        c1, c2, c3 = st.columns(3)
        c1.metric("Route",   t.get("route_id",""))
        c2.metric("Status",  _STATUS_ICON.get(t.get("status",""),"⚪") + " " + t.get("status","").replace("_"," "))
        c3.metric("Delay",   f"{t.get('delay_minutes',0)} min")
        st.markdown(
            f"**Carrier:** {t.get('carrier','')} &nbsp;|&nbsp; "
            f"**Route:** {t.get('origin','')} → {t.get('destination','')} &nbsp;|&nbsp; "
            f"**Mode:** {_MODE_ICON.get(t.get('mode',''),'')} {t.get('mode','')}  \n"
            f"**Scheduled:** {str(t.get('scheduled_dep',''))[:16].replace('T',' ')} &nbsp;|&nbsp; "
            f"**Gate/Platform:** {t.get('gate') or t.get('platform') or '—'} &nbsp;|&nbsp; "
            f"**Updated:** {str(t.get('updated_at',''))[:19].replace('T',' ')} UTC"
        )
        return

    st.markdown(result_str)


# ── UI ────────────────────────────────────────────────────────────────────────

def _run_quick(prompt: str) -> None:
    st.session_state.tr_messages.append({"role": "user", "content": prompt})
    with st.spinner("Querying Kafka via MCP tool…"):
        tool, res = _call_tool(prompt)
        # Retry once if the result is empty (Kafka partition assignment lag)
        try:
            data = json.loads(res)
            is_empty = (
                data.get("count", 1) == 0
                or data.get("delayed_count", 1) == 0
                or data.get("events", [1]) == []
            )
            if is_empty and tool not in ("error", "transit_inject_delay"):
                tool, res = _call_tool(prompt)
        except Exception:
            pass
    st.session_state.tr_messages.append({"role": "assistant", "tool": tool, "raw": res})


st.title("🤖 Transit Agent Chat")
st.caption("Ask questions about live transit data via MCP tools")

# ── Quick-action buttons ──────────────────────────────────────────────────────
st.subheader("Quick actions")

row1 = st.columns(4)
for col, (label, prompt) in zip(row1, {
    "📡 Latest events":        "Show me the latest transit events",
    "🟡 All delayed trips":    "Show all delayed trips",
    "✈️ Delayed flights":      "Show delayed flights",
    "🚆 Delayed trains":       "Show delayed trains",
}.items()):
    if col.button(label, use_container_width=True):
        _run_quick(prompt)

row2 = st.columns(4)
for col, (label, prompt) in zip(row2, {
    "🛫 AA-101 status":        "Get status for route AA-101",
    "🛬 UA-301 status":        "Get status for route UA-301",
    "🏆 Carrier ranking":      "Show carrier on-time ranking",
    "🚨 Inject AA-101 delay":  "Inject 10 delay events for route AA-101",
}.items()):
    if col.button(label, use_container_width=True):
        _run_quick(prompt)

st.divider()

# ── Chat history ──────────────────────────────────────────────────────────────
for msg in st.session_state.tr_messages:
    with st.chat_message(msg["role"]):
        if "content" in msg:
            # plain text message (user input or welcome message)
            st.markdown(msg["content"])
        else:
            # rich widget result
            _render_result(msg.get("tool", "error"), msg.get("raw", "{}"))
        if msg.get("tool"):
            st.caption(f"🔧 MCP tool: `{msg['tool']}`")

# ── Chat input ────────────────────────────────────────────────────────────────
if prompt := st.chat_input("Ask about routes, delays, carriers, or a specific trip ID…"):
    st.session_state.tr_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Querying Kafka via MCP tool…"):
            tool_name, result = _call_tool(prompt)
            try:
                data = json.loads(result)
                is_empty = (
                    data.get("count", 1) == 0
                    or data.get("delayed_count", 1) == 0
                    or data.get("events", [1]) == []
                )
                if is_empty and tool_name not in ("error", "transit_inject_delay"):
                    tool_name, result = _call_tool(prompt)
            except Exception:
                pass
        _render_result(tool_name, result)
        st.caption(f"🔧 MCP tool: `{tool_name}`")
    st.session_state.tr_messages.append({
        "role": "assistant", "tool": tool_name, "raw": result,
    })
