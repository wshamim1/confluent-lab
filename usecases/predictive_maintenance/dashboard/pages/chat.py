"""
dashboard/pages/chat.py — MCP Agent Chat panel for the Streamlit dashboard.

Lets you interact with the four MCP tools via natural language, exactly like
the WatsonX Orchestrate chat interface shown in the demo.

Recognised intents (keyword-based router):
  • "sensor" / "reading" / "latest"         → kafka_read_sensors
  • "alert" / "anomaly" / "equipment"       → kafka_read_alerts
  • "active anomal" / "current anomal"      → list_active_anomalies
  • "history" / "part" / "maintenance"      → get_part_history   (needs machine name)
  • "status" / "health" / "score"           → get_machine_status (needs machine name)
  • "work order" / "create" / "ticket"      → create_work_order  (needs machine + sensor + severity)
  • "open ticket" / "list order"            → get_work_orders
  • "acknowledge" / "ack"                   → acknowledge_alert  (needs machine + sensor)
  • "inject" / "test event" / "simulate"    → produce_test_event (needs value)

You can also paste a raw alert JSON and it will be processed like the agent does.

Run (alongside the main dashboard):
    KAFKA_ENV=onprem streamlit run dashboard/app.py
    # chat panel auto-appears as "chat" in the sidebar page list
"""

import json
import re
import sys
from datetime import datetime, timezone

import streamlit as st

sys.path.insert(0, ".")
sys.path.insert(0, "usecases/predictive_maintenance/mcp_server")

from server import (
    tool_create_work_order,
    tool_get_part_history,
    tool_get_machine_status,
    tool_get_work_orders,
    tool_kafka_read_alerts,
    tool_kafka_read_sensors,
    tool_list_active_anomalies,
    tool_acknowledge_alert,
    tool_produce_test_event,
    tool_check_parts_availability,
    tool_get_recommended_parts,
    tool_get_asset_info,
    tool_search_customers,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MCP Agent Chat — Predictive Maintenance",
    page_icon="🤖",
    layout="wide",
)

# ── Session state ─────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "👋 Hi! I'm the predictive maintenance agent powered by Confluent MCP tools.\n\n"
                "**What I can do:**\n"
                "- 📊 *Read the latest sensor readings from Kafka*\n"
                "- 🚨 *Show equipment alerts*\n"
                "- 🔧 *Get part history for turbine-1* (or compressor-1, pump-1, hvac-1)\n"
                "- 📋 *Create a work order for turbine-1 critical temperature anomaly*\n\n"
                "You can also paste a raw alert JSON and I'll process it end-to-end."
            ),
        }
    ]

# ── Known machines ─────────────────────────────────────────────────────────────
MACHINES      = ["turbine-1", "compressor-1", "pump-1", "hvac-1"]
SENSOR_TYPES  = ["temperature", "vibration", "pressure", "flow_rate", "rpm", "humidity"]
SEVERITIES    = ["critical", "warning", "info"]


# ── Intent detection ──────────────────────────────────────────────────────────

def _extract_machine(text: str) -> str:
    for m in MACHINES:
        if m in text:
            return m
    return ""

def _extract_sensor(text: str) -> str:
    for s in SENSOR_TYPES:
        if s in text:
            return s
    return "temperature"

def _extract_severity(text: str) -> str:
    for sev in SEVERITIES:
        if sev in text:
            return sev
    return "warning"

def _extract_limit(text: str) -> int:
    m = re.search(r"\b(\d+)\b", text)
    return min(int(m.group(1)), 50) if m else 10

def _is_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    return None


# ── Tool dispatch ─────────────────────────────────────────────────────────────

def _call_tool(user_input: str) -> tuple[str, str]:
    """
    Route user input to the right MCP tool.
    Returns (tool_name, result_str).
    """
    text = user_input.lower()

    # Raw JSON alert paste → full agent flow
    raw = _is_json(user_input)
    if raw and "machine_id" in raw:
        machine  = raw.get("machine_id", "unknown")
        sensor   = raw.get("sensor_type", "temperature")
        severity = raw.get("severity", "warning")
        score    = float(raw.get("anomaly_score", 0.0))
        avg      = float(raw.get("avg_value", 0.0))
        unit     = raw.get("unit", "")
        facility = raw.get("facility", "unknown")
        hist = json.loads(tool_get_part_history({"machine_id": machine}))
        wo   = json.loads(tool_create_work_order({
            "machine_id": machine, "sensor_type": sensor, "severity": severity,
            "anomaly_score": score, "avg_value": avg, "unit": unit, "facility": facility,
            "detected_at": raw.get("detected_at", datetime.now(timezone.utc).isoformat()),
        }))
        return "create_work_order", json.dumps({"part_history": hist, "work_order": wo}, indent=2)

    # Acknowledge alert
    if any(w in text for w in ["acknowledge", "ack", "mark as handled", "dismiss"]):
        machine = _extract_machine(text)
        sensor  = _extract_sensor(text)
        if not machine:
            return "error", "Please specify a machine name to acknowledge (turbine-1, compressor-1, pump-1, hvac-1)."
        return "acknowledge_alert", tool_acknowledge_alert({
            "machine_id": machine, "sensor_type": sensor, "acknowledged_by": "chat-user",
        })

    # Inject / produce test event
    if any(w in text for w in ["inject", "test event", "simulate", "produce", "fake"]):
        machine = _extract_machine(text) or "turbine-1"
        sensor  = _extract_sensor(text)
        # try to extract a numeric value from the prompt
        m_val   = re.search(r"\b(\d+(?:\.\d+)?)\b", text)
        value   = float(m_val.group(1)) if m_val else 500.0
        return "produce_test_event", tool_produce_test_event({
            "machine_id": machine, "sensor_type": sensor, "value": value,
        })

    # List open work orders
    if any(w in text for w in ["open ticket", "list order", "open order", "existing ticket", "existing order"]):
        machine = _extract_machine(text)
        return "get_work_orders", tool_get_work_orders({"machine_id": machine})

    # Machine health / status
    if any(w in text for w in ["status", "health", "score", "how is", "condition"]):
        machine = _extract_machine(text)
        if not machine:
            return "error", "Please specify a machine name (turbine-1, compressor-1, pump-1, hvac-1)."
        return "get_machine_status", tool_get_machine_status({"machine_id": machine})

    # Active anomalies (current / deduped)
    if any(w in text for w in ["active anomal", "current anomal", "live anomal", "right now"]):
        return "list_active_anomalies", tool_list_active_anomalies({})

    # Search / list customers — MUST be before the generic "customer" asset check
    if any(w in text for w in ["search customer", "list customer", "find customer", "all customer",
                                "energy company", "chemical company", "show customer", "all clients"]):
        industry = ""
        for ind in ["energy", "chemical", "manufacturing", "utilities"]:
            if ind in text:
                industry = ind
                break
        return "search_customers", tool_search_customers({"query": "", "industry": industry})

    # Recommended parts — MUST be before generic "part" / inventory check
    if any(w in text for w in ["recommend", "what to buy", "what do i need", "what parts"]):
        machine  = _extract_machine(text)
        sensor   = _extract_sensor(text)
        severity = _extract_severity(text)
        if not machine:
            return "error", "Please specify a machine name for part recommendations."
        return "get_recommended_parts", tool_get_recommended_parts({
            "machine_id": machine, "sensor_type": sensor, "severity": severity,
        })

    # Parts / inventory — MUST be before "part history" (which also matches "part")
    if any(w in text for w in ["stock", "inventory", "spare", "bearing", "valve", "seal", "supplier",
                                "availability", "parts avail", "check part"]):
        machine = _extract_machine(text)
        sensor  = _extract_sensor(text) if any(s in text for s in SENSOR_TYPES) else ""
        part_match = re.search(r'\b([A-Z]{2,6}-[A-Z0-9]{2,6})\b', user_input.upper())
        part_id    = part_match.group(1) if part_match else ""
        return "check_parts_availability", tool_check_parts_availability({
            "machine_id": machine, "sensor_type": sensor, "part_id": part_id,
        })

    # "parts for X" → inventory, but NOT if "history" is also present
    if "part" in text and "history" not in text and any(w in text for w in ["available", "stock", "filter", "parts for"]):
        machine = _extract_machine(text)
        sensor  = _extract_sensor(text) if any(s in text for s in SENSOR_TYPES) else ""
        if machine:
            return "check_parts_availability", tool_check_parts_availability({
                "machine_id": machine, "sensor_type": sensor, "part_id": "",
            })

    # Work order intent
    if any(w in text for w in ["work order", "create", "ticket", "issue", "raise"]):
        machine  = _extract_machine(text)
        if not machine:
            return "error", "Please specify a machine name (turbine-1, compressor-1, pump-1, hvac-1)."
        sensor   = _extract_sensor(text)
        severity = _extract_severity(text)
        return "create_work_order", tool_create_work_order({
            "machine_id": machine, "sensor_type": sensor, "severity": severity,
        })

    # Part history — "history", "maintenance", "repair", "technician" (removed bare "who" — too generic)
    if any(w in text for w in ["history", "maintenance", "repair", "technician", "part history"]):
        machine = _extract_machine(text)
        if not machine:
            return "error", "Please specify a machine name (turbine-1, compressor-1, pump-1, hvac-1)."
        return "get_part_history", tool_get_part_history({"machine_id": machine})

    # Alerts intent
    if any(w in text for w in ["alert", "anomaly", "equipment", "critical", "warning"]):
        limit = _extract_limit(text)
        return "kafka_read_alerts", tool_kafka_read_alerts({"limit": limit})

    # Asset / customer info — generic, after specific customer searches above
    # also catches "tell me about cust-2055" / "about turbine-1"
    if any(w in text for w in ["asset", "customer", "warranty", "sla", "contract", "owner",
                                "who owns", "client", "who is the customer", "who owns this",
                                "tell me about", "about cust", "info on", "details"]):
        machine    = _extract_machine(text)
        cust_match = re.search(r'cust-\d+', text, re.IGNORECASE)
        cust_id    = cust_match.group(0).upper() if cust_match else ""
        if cust_id:
            return "get_asset_info", tool_get_asset_info({"customer_id": cust_id})
        if machine:
            return "get_asset_info", tool_get_asset_info({"machine_id": machine})
        # no machine and no customer id → list all customers
        return "search_customers", tool_search_customers({"query": "", "industry": ""})

    # Sensor readings (default)
    machine = _extract_machine(text)
    limit   = _extract_limit(text)
    return "kafka_read_sensors", tool_kafka_read_sensors({"limit": limit, "machine_id": machine})


# ── Response formatter ────────────────────────────────────────────────────────

def _format_response(tool_name: str, result_str: str) -> str:
    if tool_name == "error":
        return f"⚠️ {result_str}"

    try:
        data = json.loads(result_str)
    except json.JSONDecodeError:
        return result_str

    # ── Sensor readings ────────────────────────────────────────────────────
    if tool_name == "kafka_read_sensors":
        msgs = data.get("messages", [])
        if not msgs:
            return "No sensor readings found in the topic yet."
        lines = [f"📊 **Latest {len(msgs)} sensor readings** from `sensor-readings`:\n"]
        for m in msgs:
            v = m.get("value", {})
            val   = v.get("value", "?")
            unit  = v.get("unit", "")
            mid   = v.get("machine_id", "?")
            stype = v.get("sensor_type", "?")
            ts    = v.get("timestamp", "")[:19].replace("T", " ")
            flag  = ""
            # rough anomaly highlight
            if stype == "temperature" and isinstance(val, float) and val > 300:
                flag = " 🔴 **ANOMALY**"
            elif stype == "vibration" and isinstance(val, float) and val > 10:
                flag = " 🔴 **ANOMALY**"
            lines.append(f"- `{mid}` / {stype}: **{val:.2f} {unit}**{flag}  _{ts}_")
        return "\n".join(lines)

    # ── Equipment alerts ───────────────────────────────────────────────────
    if tool_name == "kafka_read_alerts":
        msgs = data.get("messages", [])
        if not msgs:
            return "✅ No equipment alerts in the topic — all systems normal."
        lines = [f"🚨 **{len(msgs)} equipment alerts** from `equipment-alerts`:\n"]
        sev_icon = {"critical": "🔴", "warning": "🟡", "info": "🟢"}
        for m in msgs:
            v    = m.get("value", {})
            sev  = v.get("severity", "?")
            icon = sev_icon.get(sev, "⚪")
            lines.append(
                f"- {icon} `{v.get('machine_id','?')}` / {v.get('sensor_type','?')}  "
                f"score={v.get('anomaly_score','?')}  _{v.get('detected_at','')[:19]}_"
            )
        return "\n".join(lines)

    # ── Part history ───────────────────────────────────────────────────────
    if tool_name == "get_part_history":
        machine    = data.get("machine_id", "?")
        technician = data.get("responsible_technician", "?")
        history    = data.get("history", [])
        lines = [
            f"🔧 **Part history for `{machine}`**",
            f"👤 Responsible technician: **{technician}**\n",
        ]
        if not history:
            lines.append("_No history records found._")
        for h in history:
            lines.append(
                f"- **{h['date']}** — {h['part']} ({h['action']}) "
                f"by {h['technician']}: _{h['notes']}_"
            )
        return "\n".join(lines)

    # ── Machine health ─────────────────────────────────────────────────────
    if tool_name == "get_machine_status":
        machine    = data.get("machine_id", "?")
        health     = data.get("health", "?")
        score      = data.get("health_score", "?")
        technician = data.get("technician", "?")
        sensors    = data.get("sensors", {})
        icon       = {"normal": "🟢", "warning": "🟡", "critical": "🔴"}.get(health, "⚪")
        lines = [f"{icon} **{machine}** health: **{health.upper()}** (score: {score}/100)", f"👤 Technician: {technician}\n"]
        for stype, s in sensors.items():
            si = {"normal": "✅", "warning": "⚠️", "critical": "🔴"}.get(s.get("status", ""), "❓")
            lines.append(f"- {si} {stype}: **{s['value']} {s['unit']}** ({s['status']})")
        return "\n".join(lines)

    # ── Active anomalies ───────────────────────────────────────────────────
    if tool_name == "list_active_anomalies":
        count = data.get("active_count", 0)
        age   = data.get("max_age_minutes", 30)
        anoms = data.get("anomalies", [])
        if not anoms:
            return f"✅ No active anomalies in the last {age} minutes."
        sev_icon = {"critical": "🔴", "warning": "🟡", "info": "🟢"}
        lines = [f"🚨 **{count} active anomalies** (last {age} min):\n"]
        for a in anoms:
            icon = sev_icon.get(a.get("severity", ""), "⚪")
            lines.append(f"- {icon} `{a.get('machine_id','?')}` / {a.get('sensor_type','?')}  score={a.get('anomaly_score','?')}")
        return "\n".join(lines)

    # ── Acknowledge alert ──────────────────────────────────────────────────
    if tool_name == "acknowledge_alert":
        ack    = data.get("acknowledgement", {})
        status = data.get("status", "?")
        return (
            f"✅ Alert acknowledged (`{status}`)\n"
            f"- Machine: `{ack.get('machine_id','?')}`\n"
            f"- Sensor: {ack.get('sensor_type','?')}\n"
            f"- By: {ack.get('acknowledged_by','?')}\n"
            f"- At: {str(ack.get('acknowledged_at',''))[:19].replace('T',' ')} UTC"
        )

    # ── Open work orders ───────────────────────────────────────────────────
    if tool_name == "get_work_orders":
        total  = data.get("total", 0)
        orders = data.get("work_orders", [])
        if not orders:
            return "📋 No open work orders found."
        sev_icon = {"critical": "🔴", "warning": "🟡", "info": "🟢"}
        lines = [f"📋 **{total} open work order(s):**\n"]
        for o in orders:
            icon = sev_icon.get(o.get("severity", ""), "⚪")
            url  = o.get("url", "")
            link = f" — [{o['id']}]({url})" if url else f" — `{o.get('id','?')}`"
            lines.append(f"- {icon} `{o.get('machine_id','?')}` / {o.get('sensor_type','?')}{link}  notified: {o.get('notified','?')}")
        return "\n".join(lines)

    # ── Parts availability ─────────────────────────────────────────────────
    if tool_name == "check_parts_availability":
        parts = data.get("parts", [])
        mach  = data.get("machine_id", "all")
        stype = data.get("sensor_type", "all")
        if not parts:
            return f"📦 No parts found for machine=`{mach}` sensor=`{stype}`."
        status_icon = {"in_stock": "✅", "low_stock": "⚠️", "out_of_stock": "🔴"}
        lines = [f"📦 **{len(parts)} parts** for `{mach}` / `{stype}`:\n"]
        for p in parts:
            icon = status_icon.get(p.get("stock_status",""), "❓")
            lines.append(
                f"- {icon} `{p['part_id']}` **{p['name']}**  "
                f"qty={p['qty_on_hand']}  ${p['unit_cost']:,}  lead={p['lead_days']}d  _{p['supplier']}_"
            )
        return "\n".join(lines)

    # ── Recommended parts ──────────────────────────────────────────────────
    if tool_name == "get_recommended_parts":
        recs  = data.get("recommendations", [])
        cost  = data.get("estimated_parts_cost", 0)
        sla_h = data.get("sla_response_h", 24)
        cust  = data.get("customer", "?")
        urg_icon = {"stock_ok": "✅", "order_soon": "🟡", "order_now": "🔴", "urgent_order": "🚨"}
        lines = [
            f"🔩 **Part recommendations** for `{data.get('machine_id')}` / {data.get('sensor_type')}",
            f"👤 Customer: **{cust}**  |  SLA: **{sla_h}h response**\n",
        ]
        for r in recs:
            icon   = urg_icon.get(r.get("urgency",""), "❓")
            can    = "✓ meets SLA" if r.get("can_meet_sla") else "✗ misses SLA"
            lines.append(
                f"- {icon} `{r['part_id']}` **{r['name']}**  qty={r['qty_on_hand']}  "
                f"${r['unit_cost']:,}  lead={r['lead_days']}d  _{can}_"
            )
        if cost > 0:
            lines.append(f"\n💰 **Estimated order cost: ${cost:,.0f}**")
        return "\n".join(lines)

    # ── Asset info ──────────────────────────────────────────────────────────
    if tool_name == "get_asset_info":
        asset = data.get("asset", {})
        cust  = data.get("customer", {})
        ws    = data.get("warranty_status", "?")
        sla   = data.get("sla_tier", "?")
        ws_icon = "✅" if ws == "active" else "⚠️"
        sla_icon = {"gold": "🥇", "silver": "🥈", "bronze": "🥉"}.get(sla, "")
        lines = [
            f"🏭 **Asset: {asset.get('asset_name','?')}**  (`{data.get('machine_id','?')}`)\n",
            f"- **Model:** {asset.get('model','?')}  |  Serial: `{asset.get('serial','?')}`",
            f"- **Customer:** {asset.get('customer_name','?')} ({asset.get('customer_id','?')})",
            f"- **Contact:** {asset.get('contact_name','?')} — {asset.get('contact_email','?')}",
            f"- **Site:** {asset.get('site','?')}  |  Installed: {asset.get('install_date','?')}",
            f"- **Warranty:** {ws_icon} {ws} (expires {asset.get('warranty_expiry','?')})",
            f"- **SLA:** {sla_icon} {sla.upper()} — {asset.get('sla_response_h','?')}h response",
            f"- **Next service:** {asset.get('next_service','?')}",
        ]
        if cust:
            lines.append(f"\n👔 **Account manager:** {cust.get('account_manager','?')} — {cust.get('am_email','?')}")
        return "\n".join(lines)

    # ── Customer search ────────────────────────────────────────────────────
    if tool_name == "search_customers":
        customers = data.get("customers", [])
        if not customers:
            return "🔍 No customers found matching your query."
        lines = [f"🏢 **{len(customers)} customer(s) found:**\n"]
        for c in customers:
            lines.append(
                f"- **{c['name']}** (`{c['customer_id']}`)  "
                f"industry: {c['industry']}  "
                f"assets: {len(c['assets'])}  "
                f"contract ends: {c['contract_end']}  "
                f"value: ${c['annual_value']:,}"
            )
            lines.append(f"  👔 AM: {c['account_manager']} — {c['am_email']}")
        return "\n".join(lines)

    # ── Produce test event ─────────────────────────────────────────────────
    if tool_name == "produce_test_event":
        rec    = data.get("record", {})
        status = data.get("status", "?")
        return (
            f"🧪 Test event **{status}** to `sensor-readings`\n"
            f"- Machine: `{rec.get('machine_id','?')}`\n"
            f"- Sensor: {rec.get('sensor_type','?')} = **{rec.get('value','?')} {rec.get('unit','')}**\n"
            f"- Timestamp: {str(rec.get('timestamp',''))[:19].replace('T',' ')} UTC"
        )

    # ── Work order (including raw JSON path) ───────────────────────────────
    if tool_name == "create_work_order":
        # Might be wrapped with part_history from the JSON paste path
        wo_data   = data.get("work_order") if "work_order" in data else data
        hist_data = data.get("part_history")

        wo       = wo_data.get("work_order", wo_data)
        notified = wo_data.get("notified", "")
        mock     = wo.get("mock", False)

        lines = ["📋 **Work order created**\n"]
        lines.append(f"- **ID:** `{wo.get('id', '?')}`")
        lines.append(f"- **Title:** {wo.get('title', '?')}")
        lines.append(f"- **Severity:** {wo.get('severity', '?')}")
        lines.append(f"- **Notified:** {notified}")
        url = wo.get("url", "")
        if url:
            lines.append(f"- **URL:** [{url}]({url})")
        if mock:
            lines.append("\n_ℹ️ Mock work order — add `LINEAR_API_KEY` to `.env` for real Linear issues._")

        if hist_data:
            technician = hist_data.get("responsible_technician", "")
            history    = hist_data.get("history", [])
            lines.append(f"\n🔧 **Part history** ({len(history)} records, technician: {technician})")
            for h in history[:3]:
                lines.append(f"- {h['date']} — {h['part']} ({h['action']}): _{h['notes']}_")

        return "\n".join(lines)

    return result_str


# ── UI ────────────────────────────────────────────────────────────────────────

st.title("🤖 MCP Agent Chat")
st.caption("Ask questions about your Kafka topics or trigger maintenance actions via MCP tools")

# ── Quick-action buttons (2 rows × 4) ─────────────────────────────────────────
def _run_quick(prompt: str) -> None:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.spinner("Calling MCP tool…"):
        tn, res = _call_tool(prompt)
    resp = _format_response(tn, res)
    st.session_state.messages.append({"role": "assistant", "content": resp, "tool": tn})

st.subheader("Quick actions")
row1 = st.columns(4)
for col, (label, prompt) in zip(row1, {
    "📊 Latest readings":   "Read the latest sensor readings from Kafka",
    "🚨 Active anomalies":  "Show active anomalies right now",
    "💚 turbine-1 status":  "What is the health status of turbine-1",
    "📋 Open work orders":  "List open work orders",
}.items()):
    if col.button(label, use_container_width=True):
        _run_quick(prompt)

row2 = st.columns(4)
for col, (label, prompt) in zip(row2, {
    "🔧 turbine-1 history":     "Get part history for turbine-1",
    "✅ Acknowledge turbine-1":  "Acknowledge turbine-1 temperature alert",
    "🧪 Inject test event":      "Inject a test event value 500 for turbine-1 temperature",
    "📝 Create work order":      "Create a critical work order for turbine-1 temperature anomaly",
}.items()):
    if col.button(label, use_container_width=True):
        _run_quick(prompt)

st.caption("📦 Inventory & Customer systems")
row3 = st.columns(4)
for col, (label, prompt) in zip(row3, {
    "📦 Parts for turbine-1":       "Check parts availability for turbine-1 vibration",
    "🔩 Recommend parts":            "Recommend parts for turbine-1 critical temperature anomaly",
    "🏭 turbine-1 asset info":       "Get asset info for turbine-1",
    "🏢 List all customers":         "List all customers",
}.items()):
    if col.button(label, use_container_width=True):
        _run_quick(prompt)

st.divider()

# Chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("tool"):
            st.caption(f"🔧 MCP tool called: `{msg['tool']}`")

# Chat input
if prompt := st.chat_input("Ask about sensors, alerts, status, work orders, or type a machine name…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Calling MCP tool…"):
            tool_name, result = _call_tool(prompt)
        response = _format_response(tool_name, result)
        st.markdown(response)
        st.caption(f"🔧 MCP tool called: `{tool_name}`")

    st.session_state.messages.append({
        "role": "assistant",
        "content": response,
        "tool": tool_name,
    })
