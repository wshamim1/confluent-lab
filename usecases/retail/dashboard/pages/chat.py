"""
usecases/retail/dashboard/pages/chat.py — Retail MCP Agent Chat.

Lets you query live retail data via natural language. Intent keywords
route to the correct MCP tool, results rendered as rich Streamlit widgets.

Recognised intents
------------------
  "top" / "spender" / "spend"         → retail_top_shoppers
  "inactive" / "reminder" / "silent"  → retail_inactive_customers
  "return" / "returner"               → retail_high_returners
  "category" / "breakdown"            → retail_category_breakdown
  "profile" / "C0\d\d"               → retail_customer_profile
  "recent" / "orders" / "latest"      → retail_recent_orders
  "send" / "remind" / "email"         → retail_send_reminder
"""

import json
import re
import sys
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

sys.path.insert(0, ".")
sys.path.insert(0, "usecases/retail/mcp_server")
sys.path.insert(0, "usecases/retail")

from server import (
    tool_retail_top_shoppers,
    tool_retail_inactive_customers,
    tool_retail_high_returners,
    tool_retail_category_breakdown,
    tool_retail_customer_profile,
    tool_retail_recent_orders,
    tool_retail_send_reminder,
)
from topics import CUSTOMERS, CUSTOMER_MAP

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Retail Agent Chat — Confluent",
    page_icon="🤖",
    layout="wide",
)

# ── Session state ──────────────────────────────────────────────────────────────
if "retail_messages" not in st.session_state:
    cid_list = ", ".join(c["customer_id"] for c in CUSTOMERS[:6]) + " …"
    st.session_state.retail_messages = [
        {
            "role": "assistant",
            "content": (
                "👋 Hi! I'm the Retail Analytics Agent — ask me about your customers and orders.\n\n"
                "**What I can do:**\n"
                "- 🏆 *Rank customers by total spend*\n"
                "- 😴 *Find inactive customers (no orders in N days)*\n"
                "- ↩️ *Identify high-return customers*\n"
                "- 📦 *Revenue breakdown by product category*\n"
                "- 👤 *Full profile for a specific customer (e.g. C001)*\n"
                "- 🧾 *Show recent orders*\n"
                "- 📧 *Send re-engagement reminder to a customer*\n\n"
                f"Customer IDs: `{cid_list}`"
            ),
        }
    ]

# ── Intent helpers ─────────────────────────────────────────────────────────────
def _extract_customer_id(text: str) -> str:
    m = re.search(r'\b(C\d{3})\b', text.upper())
    return m.group(1) if m else ""

def _extract_days(text: str) -> int:
    m = re.search(r'\b(\d+)\s*day', text.lower())
    return int(m.group(1)) if m else 7

def _extract_top_n(text: str) -> int:
    m = re.search(r'\btop\s*(\d+)\b', text.lower())
    return int(m.group(1)) if m else 10

def _extract_threshold(text: str) -> float:
    m = re.search(r'(\d+)\s*%', text)
    return int(m.group(1)) / 100.0 if m else 0.3

# ── Tool dispatch ──────────────────────────────────────────────────────────────
def _call_tool(user_input: str) -> tuple[str, str]:
    text = user_input.lower()
    cid  = _extract_customer_id(user_input)

    # Send reminder (check before inactive so "send reminder to C001" routes correctly)
    if any(w in text for w in ["send", "remind", "email", "re-engage", "reengage"]):
        if not cid:
            return "error", "Please specify a customer ID (e.g. C001)."
        return "retail_send_reminder", tool_retail_send_reminder({"customer_id": cid})

    # Customer profile
    if cid or any(w in text for w in ["profile", "history", "customer detail"]):
        if not cid:
            return "error", f"Please specify a customer ID (e.g. C001–C020)."
        return "retail_customer_profile", tool_retail_customer_profile({"customer_id": cid})

    # Top spenders
    if any(w in text for w in ["top", "spender", "spend", "highest", "best customer", "revenue"]):
        return "retail_top_shoppers", tool_retail_top_shoppers({"top_n": _extract_top_n(text)})

    # Inactive
    if any(w in text for w in ["inactive", "silent", "not shopping", "no order", "haven't shopped",
                                "reminder", "who hasn't"]):
        return "retail_inactive_customers", tool_retail_inactive_customers({"days": _extract_days(text)})

    # High returners
    if any(w in text for w in ["return", "returner", "refund", "return rate", "returning"]):
        return "retail_high_returners", tool_retail_high_returners({"threshold": _extract_threshold(text)})

    # Category breakdown
    if any(w in text for w in ["category", "breakdown", "product", "segment spend", "what sells"]):
        return "retail_category_breakdown", tool_retail_category_breakdown({})

    # Recent orders (default)
    return "retail_recent_orders", tool_retail_recent_orders({"limit": 20})


# ── Rich renderers ─────────────────────────────────────────────────────────────
_SEG_COLOUR = {"vip": "🟣", "premium": "🔵", "regular": "⚪"}

def _render_result(tool: str, result_str: str) -> None:
    if tool == "error":
        st.warning(result_str)
        return
    try:
        data = json.loads(result_str)
    except Exception:
        st.markdown(result_str)
        return

    # ── Top shoppers ──────────────────────────────────────────────────────────
    if tool == "retail_top_shoppers":
        shoppers = data.get("shoppers", [])
        if not shoppers:
            st.info("No completed orders found yet.")
            return
        st.markdown(f"🏆 **Top {data.get('top_n',10)} Customers by Spend**")
        rows = [{
            "Rank":        i+1,
            "Customer":    s["name"],
            "Segment":     _SEG_COLOUR.get(s["segment"],"") + " " + s["segment"],
            "Total Spend": f"${s['total_spend']:,.2f}",
            "Orders":      s["order_count"],
            "Avg Basket":  f"${s['avg_basket']:,.2f}",
        } for i, s in enumerate(shoppers)]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        return

    # ── Inactive customers ────────────────────────────────────────────────────
    if tool == "retail_inactive_customers":
        customers = data.get("customers", [])
        threshold = data.get("inactive_days_threshold", 7)
        if not customers:
            st.success(f"✅ All customers ordered within the last {threshold} days!")
            return
        st.markdown(f"😴 **{data['count']} Inactive Customers** (no orders in {threshold}+ days)")
        rows = [{
            "Customer":     c["name"],
            "Segment":      _SEG_COLOUR.get(c["segment"],"") + " " + c["segment"],
            "Email":        c["email"],
            "Last Order":   c["last_order"][:16].replace("T"," ") if c["last_order"] != "never" else "never",
            "Days Inactive": c["days_inactive"],
        } for c in customers]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("💡 Tip: *'Send reminder to C001'* to trigger a re-engagement email")
        return

    # ── High returners ────────────────────────────────────────────────────────
    if tool == "retail_high_returners":
        customers = data.get("customers", [])
        threshold = data.get("threshold_pct", 30)
        if not customers:
            st.success(f"✅ No customers above {threshold}% return rate.")
            return
        st.markdown(f"↩️ **{data['count']} High Returners** (return rate ≥ {threshold}%)")
        rows = [{
            "Customer":     c["name"],
            "Segment":      _SEG_COLOUR.get(c["segment"],"") + " " + c["segment"],
            "Orders":       c["order_count"],
            "Returns":      c["return_count"],
            "Return Rate":  f"{c['return_rate']}%",
            "Top Reasons":  " · ".join(c.get("top_reasons",[])),
        } for c in customers]
        df = pd.DataFrame(rows)
        st.dataframe(
            df.style.background_gradient(subset=[], cmap="RdYlGn_r"),
            use_container_width=True, hide_index=True,
        )
        return

    # ── Category breakdown ────────────────────────────────────────────────────
    if tool == "retail_category_breakdown":
        cats = data.get("categories", [])
        if not cats:
            st.info("No order data yet.")
            return
        st.markdown(f"📦 **Revenue by Category** — total: `${data.get('total_revenue',0):,.2f}`")
        c1, c2 = st.columns([1, 1])
        with c1:
            rows = [{
                "Category":  c["category"],
                "Revenue":   f"${c['total_spend']:,.2f}",
                "Items Sold": c["items_sold"],
            } for c in cats]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        with c2:
            import plotly.express as px
            fig = px.pie(
                pd.DataFrame(cats), values="total_spend", names="category",
                hole=0.4, color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig.update_layout(height=260, margin=dict(l=0,r=0,t=10,b=0),
                              showlegend=True)
            st.plotly_chart(fig, use_container_width=True)
        return

    # ── Customer profile ──────────────────────────────────────────────────────
    if tool == "retail_customer_profile":
        if "error" in data:
            st.error(data["error"])
            return
        st.markdown(f"### 👤 {data['name']} (`{data['customer_id']}`)")
        st.caption(f"{_SEG_COLOUR.get(data['segment'],'')} {data['segment']} · {data['email']}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Spend",   f"${data['total_spend']:,.2f}")
        c2.metric("Orders",        data["completed_orders"])
        c3.metric("Returns",       data["total_returns"])
        c4.metric("Return Rate",   f"{data['return_rate']}%",
                  delta_color="inverse" if data["return_rate"] > 30 else "normal")
        if data["recent_orders"]:
            st.markdown("**Recent Orders:**")
            rows = [{
                "Product":   o.get("product_name",""),
                "Category":  o.get("category",""),
                "Total":     f"${float(o.get('total',0)):.2f}",
                "Status":    o.get("status",""),
                "Date":      str(o.get("ts",""))[:16].replace("T"," "),
            } for o in data["recent_orders"]]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if data["recent_returns"]:
            st.markdown("**Recent Returns:**")
            rows = [{
                "Product":  r.get("product_name",""),
                "Refund":   f"${float(r.get('refund_amount',0)):.2f}",
                "Reason":   r.get("reason",""),
                "Date":     str(r.get("ts",""))[:16].replace("T"," "),
            } for r in data["recent_returns"]]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        return

    # ── Recent orders ─────────────────────────────────────────────────────────
    if tool == "retail_recent_orders":
        orders = data.get("orders", [])
        if not orders:
            st.info("No orders yet.")
            return
        st.markdown(f"🧾 **{len(orders)} Recent Orders** (from {data.get('count',0)} total)")
        rows = [{
            "Customer":  o.get("customer_name",""),
            "Product":   o.get("product_name",""),
            "Category":  o.get("category",""),
            "Total":     f"${float(o.get('total',0)):.2f}",
            "Status":    o.get("status",""),
            "Time":      str(o.get("ts",""))[:16].replace("T"," "),
        } for o in orders]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        return

    # ── Send reminder ─────────────────────────────────────────────────────────
    if tool == "retail_send_reminder":
        if "error" in data:
            st.error(data["error"])
            return
        st.success(f"📧 **Reminder sent!**")
        c1, c2 = st.columns(2)
        c1.metric("Customer", data["name"])
        c2.metric("Segment",  _SEG_COLOUR.get(data["segment"],"") + " " + data["segment"])
        st.markdown(f"> {data['message']}")
        st.caption(f"Sent at: {str(data.get('sent_at',''))[:19].replace('T',' ')} UTC")
        return

    st.markdown(result_str)


# ── Quick action runner ────────────────────────────────────────────────────────
def _run_quick(prompt: str) -> None:
    st.session_state.retail_messages.append({"role": "user", "content": prompt})
    with st.spinner("Querying Kafka via MCP tool…"):
        tool, res = _call_tool(prompt)
        try:
            d = json.loads(res)
            is_empty = (
                not d.get("shoppers") and not d.get("customers") and
                not d.get("categories") and not d.get("orders") and
                "error" not in d and "status" not in d
            )
            if is_empty:
                tool, res = _call_tool(prompt)
        except Exception:
            pass
    st.session_state.retail_messages.append({"role": "assistant", "tool": tool, "raw": res})


# ── Page layout ────────────────────────────────────────────────────────────────
st.title("🤖 Retail Analytics Agent")
st.caption("Ask questions about customers, orders, returns, and categories via MCP tools")

# Quick action buttons
st.subheader("Quick actions")
row1 = st.columns(4)
for col, (label, prompt) in zip(row1, {
    "🏆 Top 10 spenders":       "Show top 10 customers by spend",
    "😴 Inactive customers":    "Who hasn't shopped in 7 days",
    "↩️ High returners":        "Show customers with high return rate",
    "📦 Category breakdown":    "Show revenue by product category",
}.items()):
    if col.button(label, use_container_width=True):
        _run_quick(prompt)

row2 = st.columns(4)
for col, (label, prompt) in zip(row2, {
    "👤 Profile C001":          "Show profile for customer C001",
    "👤 Profile C005 (VIP)":    "Show profile for customer C005",
    "🧾 Recent orders":         "Show recent orders",
    "📧 Remind C006":           "Send reminder to C006",
}.items()):
    if col.button(label, use_container_width=True):
        _run_quick(prompt)

st.divider()

# Chat history
for msg in st.session_state.retail_messages:
    with st.chat_message(msg["role"]):
        if "content" in msg:
            st.markdown(msg["content"])
        else:
            _render_result(msg.get("tool","error"), msg.get("raw","{}"))
        if msg.get("tool"):
            st.caption(f"🔧 MCP tool: `{msg['tool']}`")

# Chat input
if prompt := st.chat_input("Ask about customers, orders, returns, categories…"):
    st.session_state.retail_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Querying Kafka via MCP tool…"):
            tool_name, result = _call_tool(prompt)
            try:
                d = json.loads(result)
                is_empty = (
                    not d.get("shoppers") and not d.get("customers") and
                    not d.get("categories") and not d.get("orders") and
                    "error" not in d and "status" not in d
                )
                if is_empty:
                    tool_name, result = _call_tool(prompt)
            except Exception:
                pass
        _render_result(tool_name, result)
        st.caption(f"🔧 MCP tool: `{tool_name}`")
    st.session_state.retail_messages.append({
        "role": "assistant", "tool": tool_name, "raw": result,
    })
