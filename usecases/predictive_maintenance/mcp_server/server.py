"""
MCP server for the Confluent Predictive Maintenance demo.

Exposes nine tools to any MCP-compatible agent (Watson X Orchestrate, Bob, etc.):

  kafka_read_alerts      — Read the latest N messages from equipment-alerts topic
  kafka_read_sensors     — Read the latest N readings from sensor-readings topic
  get_part_history       — Look up maintenance / part-replacement history for a machine
  create_work_order      — Create a Linear (or mock) work order for a maintenance issue
  get_machine_status     — Compute a health score for a machine from its latest readings
  list_active_anomalies  — Return only currently-active anomalies (last seen < max_age_minutes)
  acknowledge_alert      — Mark an alert as acknowledged (written back to Kafka)
  get_work_orders        — List open work orders, optionally filtered by machine / severity
  produce_test_event     — Inject a synthetic sensor reading into the sensor-readings topic

Run directly (stdio transport, for use with Bob MCP config or Orchestrate):
    python3 mcp_server/server.py

Environment variables (in .env):
    KAFKA_ENV                cloud | onprem
    CONFLUENT_CLOUD_API_KEY / CONFLUENT_CLOUD_API_SECRET (or VM creds)
    KAFKA_BOOTSTRAP_SERVERS
    LINEAR_API_KEY           Personal API key for Linear (optional — mock if absent)
    LINEAR_TEAM_ID           Linear team ID for new issues  (optional)
"""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

sys.path.insert(0, ".")
from auth import kafka_config

from confluent_kafka import Consumer, KafkaError, TopicPartition
from dotenv import load_dotenv

load_dotenv()

# ── MCP SDK ───────────────────────────────────────────────────────────────────
# mcp v2: FastMCP was renamed to MCPServer (mcp.server.mcpserver)
from mcp.server.mcpserver import MCPServer as FastMCP

# ── Constants ─────────────────────────────────────────────────────────────────
TOPIC_ALERTS  = "equipment-alerts"
TOPIC_SENSORS = "sensor-readings"
TOPIC_ACKS    = "alert-acknowledgements"
DEFAULT_LIMIT = 10

# ── In-memory work order store (keyed by work order id) ───────────────────────
# Populated by create_work_order; queried by get_work_orders.
# In production this would be backed by Linear / a database.
_WORK_ORDERS: dict[str, dict] = {}

# ── Sensor baselines for health scoring ───────────────────────────────────────
SENSOR_BASELINES: dict[str, dict[str, dict]] = {
    "turbine-1":   {
        "temperature": {"base": 210, "warn": 1.5, "crit": 2.0},
        "vibration":   {"base": 1.8, "warn": 3.0, "crit": 6.0},
        "rpm":         {"base": 3000,"warn": 1.2, "crit": 1.5},
    },
    "compressor-1": {
        "temperature": {"base": 85,  "warn": 1.5, "crit": 2.0},
        "pressure":    {"base": 120, "warn": 1.5, "crit": 2.0},
        "vibration":   {"base": 2.1, "warn": 3.0, "crit": 6.0},
    },
    "pump-1": {
        "pressure":    {"base": 80,  "warn": 1.5, "crit": 2.0},
        "flow_rate":   {"base": 250, "warn": 0.5, "crit": 0.3},
        "temperature": {"base": 65,  "warn": 1.5, "crit": 2.0},
    },
    "hvac-1": {
        "temperature": {"base": 22,  "warn": 1.5, "crit": 2.0},
        "humidity":    {"base": 45,  "warn": 1.5, "crit": 2.0},
        "pressure":    {"base": 14.7,"warn": 1.4, "crit": 1.8},
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM 1 — Parts & Inventory (mock ERP / warehouse system)
# In production: SAP PM, Maximo, or a REST inventory API
# ─────────────────────────────────────────────────────────────────────────────
PARTS_CATALOG: dict[str, dict] = {
    "BRG-4821":  {"name": "Main Bearing (Large)",      "compatible":["turbine-1"],                   "unit_cost": 4200,  "lead_days": 7,  "qty_on_hand": 2,  "reorder_point": 1, "supplier": "SKF Industrial",        "category": "rotating"},
    "BRG-2210":  {"name": "Aux Bearing (Medium)",      "compatible":["compressor-1","pump-1"],        "unit_cost": 980,   "lead_days": 3,  "qty_on_hand": 5,  "reorder_point": 2, "supplier": "SKF Industrial",        "category": "rotating"},
    "VLV-0934":  {"name": "Discharge Valve",           "compatible":["compressor-1"],                 "unit_cost": 1550,  "lead_days": 5,  "qty_on_hand": 1,  "reorder_point": 1, "supplier": "Flowserve Corp",        "category": "valve"},
    "SEAL-MC3":  {"name": "Mechanical Seal Kit",       "compatible":["pump-1"],                       "unit_cost": 620,   "lead_days": 2,  "qty_on_hand": 4,  "reorder_point": 2, "supplier": "John Crane",            "category": "seal"},
    "IMPEL-P1":  {"name": "Impeller Assembly",         "compatible":["pump-1"],                       "unit_cost": 2800,  "lead_days": 14, "qty_on_hand": 0,  "reorder_point": 1, "supplier": "Goulds Pumps",          "category": "rotating"},
    "FILTR-OIL": {"name": "Oil Filter (standard)",     "compatible":["compressor-1","pump-1"],        "unit_cost": 85,    "lead_days": 1,  "qty_on_hand": 20, "reorder_point": 5, "supplier": "Donaldson Co",          "category": "consumable"},
    "FILTR-AIR": {"name": "Air Filter (HVAC)",         "compatible":["hvac-1"],                       "unit_cost": 45,    "lead_days": 1,  "qty_on_hand": 15, "reorder_point": 5, "supplier": "Camfil",                "category": "consumable"},
    "BLADE-T1":  {"name": "Rotor Blade Set (turbine)", "compatible":["turbine-1"],                    "unit_cost": 18500, "lead_days": 21, "qty_on_hand": 0,  "reorder_point": 1, "supplier": "GE Vernova",            "category": "critical"},
    "SENS-VIB":  {"name": "Vibration Sensor",          "compatible":["turbine-1","compressor-1"],     "unit_cost": 320,   "lead_days": 2,  "qty_on_hand": 6,  "reorder_point": 2, "supplier": "PCB Piezotronics",      "category": "sensor"},
    "SENS-TMP":  {"name": "Temperature Sensor (PT100)","compatible":["turbine-1","compressor-1","pump-1","hvac-1"], "unit_cost": 95, "lead_days": 1, "qty_on_hand": 12, "reorder_point": 4, "supplier": "Endress+Hauser", "category": "sensor"},
    "COMP-HVAC": {"name": "HVAC Compressor Unit",      "compatible":["hvac-1"],                       "unit_cost": 6400,  "lead_days": 10, "qty_on_hand": 1,  "reorder_point": 1, "supplier": "Carrier Corp",          "category": "critical"},
    "LUBR-ISO68":{"name": "ISO 68 Turbine Oil (20L)",  "compatible":["turbine-1","compressor-1"],     "unit_cost": 120,   "lead_days": 1,  "qty_on_hand": 30, "reorder_point": 10,"supplier": "Shell Lubricants",      "category": "consumable"},
}

# sensor_type → likely parts needed
SENSOR_PART_MAP: dict[str, list[str]] = {
    "vibration":   ["BRG-4821", "BRG-2210", "SENS-VIB", "LUBR-ISO68"],
    "temperature": ["SENS-TMP", "LUBR-ISO68", "FILTR-OIL"],
    "pressure":    ["VLV-0934", "SEAL-MC3", "FILTR-OIL"],
    "flow_rate":   ["SEAL-MC3", "IMPEL-P1", "VLV-0934"],
    "rpm":         ["BRG-4821", "BRG-2210", "LUBR-ISO68"],
    "humidity":    ["FILTR-AIR", "COMP-HVAC"],
}

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM 2 — Customer & Asset Registry (mock CRM / asset management system)
# In production: Salesforce, ServiceNow, or an EAM REST API
# ─────────────────────────────────────────────────────────────────────────────
ASSET_REGISTRY: dict[str, dict] = {
    "turbine-1": {
        "asset_id":       "AST-0041",
        "asset_name":     "Gas Turbine Unit 1",
        "customer_id":    "CUST-1001",
        "customer_name":  "AcmePower Energy Ltd",
        "contact_name":   "David Chen",
        "contact_email":  "d.chen@acmepower.example.com",
        "contact_phone":  "+1-415-555-0101",
        "site":           "plant-a",
        "install_date":   "2019-03-15",
        "warranty_expiry":"2027-03-15",
        "sla_tier":       "gold",
        "sla_response_h": 4,
        "model":          "GE LM2500+G4",
        "serial":         "LM2500-GA-00412",
        "next_service":   "2025-12-01",
    },
    "compressor-1": {
        "asset_id":       "AST-0042",
        "asset_name":     "Industrial Air Compressor 1",
        "customer_id":    "CUST-1001",
        "customer_name":  "AcmePower Energy Ltd",
        "contact_name":   "David Chen",
        "contact_email":  "d.chen@acmepower.example.com",
        "contact_phone":  "+1-415-555-0101",
        "site":           "plant-a",
        "install_date":   "2020-07-22",
        "warranty_expiry":"2025-07-22",
        "sla_tier":       "silver",
        "sla_response_h": 8,
        "model":          "Atlas Copco GA 315",
        "serial":         "ATC-315-20072-B",
        "next_service":   "2025-10-15",
    },
    "pump-1": {
        "asset_id":       "AST-0091",
        "asset_name":     "Centrifugal Process Pump 1",
        "customer_id":    "CUST-2055",
        "customer_name":  "NorthStar Chemicals Inc",
        "contact_name":   "Priya Sharma",
        "contact_email":  "p.sharma@northstar.example.com",
        "contact_phone":  "+1-713-555-0188",
        "site":           "plant-b",
        "install_date":   "2021-11-05",
        "warranty_expiry":"2026-11-05",
        "sla_tier":       "gold",
        "sla_response_h": 4,
        "model":          "Grundfos CR 32-5",
        "serial":         "GF-CR32-21110-01",
        "next_service":   "2025-11-05",
    },
    "hvac-1": {
        "asset_id":       "AST-0092",
        "asset_name":     "HVAC Central Unit 1",
        "customer_id":    "CUST-2055",
        "customer_name":  "NorthStar Chemicals Inc",
        "contact_name":   "Priya Sharma",
        "contact_email":  "p.sharma@northstar.example.com",
        "contact_phone":  "+1-713-555-0188",
        "site":           "plant-b",
        "install_date":   "2022-02-18",
        "warranty_expiry":"2025-02-18",
        "sla_tier":       "bronze",
        "sla_response_h": 24,
        "model":          "Carrier AquaForce 30XW",
        "serial":         "CAR-30XW-22021-C",
        "next_service":   "2025-09-30",
    },
}

CUSTOMER_DB: dict[str, dict] = {
    "CUST-1001": {
        "name":           "AcmePower Energy Ltd",
        "industry":       "Energy & Utilities",
        "account_manager":"Sarah Mitchell",
        "am_email":       "s.mitchell@vendor.example.com",
        "contract_start": "2019-01-01",
        "contract_end":   "2028-12-31",
        "assets":         ["turbine-1", "compressor-1"],
        "open_tickets":   0,
        "annual_value":   285000,
    },
    "CUST-2055": {
        "name":           "NorthStar Chemicals Inc",
        "industry":       "Chemical Manufacturing",
        "account_manager":"Tom Okafor",
        "am_email":       "t.okafor@vendor.example.com",
        "contract_start": "2021-06-01",
        "contract_end":   "2026-05-31",
        "assets":         ["pump-1", "hvac-1"],
        "open_tickets":   0,
        "annual_value":   94000,
    },
}

# ── Mock part-history database ────────────────────────────────────────────────
# In production this would query a CMMS / EAM system via API.
PART_HISTORY: dict[str, list[dict]] = {
    "turbine-1": [
        {"date": "2024-11-05", "part": "main bearing",    "action": "replaced",   "technician": "Arun Patel",   "notes": "Bearing wear detected by vibration spike"},
        {"date": "2024-08-20", "part": "vibration sensor","action": "calibrated", "technician": "Maria Lopez",  "notes": "Routine 6-month calibration"},
        {"date": "2024-05-14", "part": "rotor blades",    "action": "inspected",  "technician": "Arun Patel",   "notes": "Visual inspection — no cracks found"},
    ],
    "compressor-1": [
        {"date": "2025-01-10", "part": "discharge valve", "action": "replaced",   "technician": "James Kim",    "notes": "Pressure drop beyond threshold"},
        {"date": "2024-10-02", "part": "oil filter",      "action": "replaced",   "technician": "Maria Lopez",  "notes": "Scheduled PM"},
        {"date": "2024-07-18", "part": "temperature sensor","action":"calibrated","technician": "James Kim",    "notes": "Offset drift corrected"},
    ],
    "pump-1": [
        {"date": "2025-02-01", "part": "mechanical seal", "action": "replaced",   "technician": "Arun Patel",   "notes": "Seal leak — unplanned repair"},
        {"date": "2024-12-15", "part": "impeller",        "action": "inspected",  "technician": "Maria Lopez",  "notes": "Erosion within acceptable limits"},
    ],
    "hvac-1": [
        {"date": "2025-01-22", "part": "air filter",      "action": "replaced",   "technician": "James Kim",    "notes": "Scheduled quarterly replacement"},
        {"date": "2024-09-30", "part": "compressor",      "action": "serviced",   "technician": "Maria Lopez",  "notes": "Annual service"},
    ],
}

TECHNICIAN_MAP: dict[str, str] = {
    "turbine-1":   "arun.patel@example.com",
    "compressor-1":"james.kim@example.com",
    "pump-1":      "arun.patel@example.com",
    "hvac-1":      "maria.lopez@example.com",
}


# ── Kafka helpers ─────────────────────────────────────────────────────────────

def _read_last_n(topic: str, n: int) -> list[dict]:
    """Consume the latest `n` messages from `topic` and return them as dicts."""
    cfg = kafka_config(
        client_id=f"mcp-server-reader-{uuid.uuid4().hex[:6]}",
        group_id=f"mcp-server-{uuid.uuid4().hex[:8]}",
    )
    cfg["auto.offset.reset"]           = "latest"
    cfg["enable.auto.commit"]          = False
    cfg["session.timeout.ms"]          = 10000
    cfg["max.poll.interval.ms"]        = 15000

    consumer = Consumer(cfg)
    messages: list[dict] = []

    try:
        meta = consumer.list_topics(topic, timeout=10)
        if topic not in meta.topics or meta.topics[topic].error:
            return [{"error": f"Topic '{topic}' not found or inaccessible"}]

        partitions = [
            TopicPartition(topic, pid)
            for pid in meta.topics[topic].partitions
        ]

        # Seek each partition to (end - n) so we get the last n total
        consumer.assign(partitions)
        lows_highs = consumer.get_watermark_offsets  # bound method

        per_partition_n = max(1, n // len(partitions))
        assigned = []
        for tp in partitions:
            low, high = consumer.get_watermark_offsets(tp, timeout=5)
            start = max(low, high - per_partition_n)
            assigned.append(TopicPartition(topic, tp.partition, start))

        consumer.assign(assigned)

        deadline_ms = 8000
        end_time    = datetime.now(timezone.utc).timestamp() + deadline_ms / 1000

        while len(messages) < n:
            if datetime.now(timezone.utc).timestamp() > end_time:
                break
            msg = consumer.poll(1.0)
            if msg is None:
                break
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    break
                continue
            try:
                value = json.loads(msg.value().decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, AttributeError):
                value = msg.value().decode("utf-8", errors="replace") if msg.value() else ""
            messages.append({
                "partition": msg.partition(),
                "offset":    msg.offset(),
                "key":       msg.key().decode("utf-8", errors="replace") if msg.key() else None,
                "value":     value,
            })

    finally:
        consumer.close()

    return messages[-n:]  # trim to exactly n if over


# ── Linear work order ─────────────────────────────────────────────────────────

def _create_linear_issue(
    title: str,
    description: str,
    machine_id: str,
    severity: str,
) -> dict:
    """Create a Linear issue. Falls back to a mock response if LINEAR_API_KEY is absent."""
    api_key = os.getenv("LINEAR_API_KEY", "")
    team_id = os.getenv("LINEAR_TEAM_ID", "")

    technician_email = TECHNICIAN_MAP.get(machine_id, "maintenance@example.com")

    if not api_key:
        # Mock response for demo / testing without a real Linear account
        issue_id = f"MNT-{uuid.uuid4().hex[:4].upper()}"
        return {
            "id":          issue_id,
            "url":         f"https://linear.app/mock/issue/{issue_id}",
            "title":       title,
            "description": description,
            "severity":    severity,
            "assignee":    technician_email,
            "created_at":  datetime.now(timezone.utc).isoformat(),
            "mock":        True,
        }

    # Real Linear GraphQL mutation
    import requests as _requests
    mutation = """
    mutation CreateIssue($title: String!, $desc: String!, $teamId: String!, $priority: Int!) {
      issueCreate(input: {
        title: $title
        description: $desc
        teamId: $teamId
        priority: $priority
      }) {
        success
        issue { id url title }
      }
    }
    """
    priority_map = {"critical": 1, "warning": 2, "info": 3}
    priority     = priority_map.get(severity.lower(), 2)

    r = _requests.post(
        "https://api.linear.app/graphql",
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        json={
            "query": mutation,
            "variables": {
                "title":    title,
                "desc":     description,
                "teamId":   team_id,
                "priority": priority,
            },
        },
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    issue = data.get("data", {}).get("issueCreate", {}).get("issue", {})
    return {
        "id":          issue.get("id"),
        "url":         issue.get("url"),
        "title":       title,
        "severity":    severity,
        "assignee":    technician_email,
        "created_at":  datetime.now(timezone.utc).isoformat(),
        "mock":        False,
    }


# ── Kafka producer helper ─────────────────────────────────────────────────────

def _produce_one(topic: str, key: str, value: dict) -> None:
    """Fire-and-forget a single JSON record to a Kafka topic."""
    from confluent_kafka import Producer as _Producer
    cfg = kafka_config(client_id=f"mcp-producer-{uuid.uuid4().hex[:6]}")
    cfg.pop("session.timeout.ms", None)
    prod = _Producer(cfg)
    prod.produce(topic, key=key.encode(), value=json.dumps(value).encode())
    prod.flush(timeout=10)


# ── Tool implementations ───────────────────────────────────────────────────────

def tool_kafka_read_alerts(arguments: dict) -> str:
    limit    = int(arguments.get("limit", DEFAULT_LIMIT))
    messages = _read_last_n(TOPIC_ALERTS, limit)
    return json.dumps({"topic": TOPIC_ALERTS, "count": len(messages), "messages": messages}, indent=2)


def tool_kafka_read_sensors(arguments: dict) -> str:
    limit      = int(arguments.get("limit", DEFAULT_LIMIT))
    machine_id = arguments.get("machine_id", "")
    messages   = _read_last_n(TOPIC_SENSORS, limit * 4 if machine_id else limit)
    if machine_id:
        messages = [
            m for m in messages
            if isinstance(m.get("value"), dict)
            and m["value"].get("machine_id") == machine_id
        ][:limit]
    return json.dumps({"topic": TOPIC_SENSORS, "count": len(messages), "messages": messages}, indent=2)


def tool_get_part_history(arguments: dict) -> str:
    machine_id = arguments.get("machine_id", "").lower().strip()
    history    = PART_HISTORY.get(machine_id, [])
    technician = TECHNICIAN_MAP.get(machine_id, "maintenance@example.com")
    return json.dumps({
        "machine_id":           machine_id,
        "responsible_technician": technician,
        "history_count":        len(history),
        "history":              history,
    }, indent=2)


def tool_create_work_order(arguments: dict) -> str:
    machine_id   = arguments.get("machine_id", "unknown")
    sensor_type  = arguments.get("sensor_type", "unknown")
    severity     = arguments.get("severity", "warning")
    anomaly_score= arguments.get("anomaly_score", 0.0)
    avg_value    = arguments.get("avg_value", 0.0)
    unit         = arguments.get("unit", "")
    facility     = arguments.get("facility", "unknown")
    detected_at  = arguments.get("detected_at", datetime.now(timezone.utc).isoformat())
    notes        = arguments.get("notes", "")

    technician   = TECHNICIAN_MAP.get(machine_id, "maintenance@example.com")

    title = (
        f"[{severity.upper()}] {sensor_type.title()} anomaly on {machine_id} "
        f"— facility {facility}"
    )

    # Build a rich Markdown description for the work order
    history     = PART_HISTORY.get(machine_id, [])
    history_md  = "\n".join(
        f"- **{h['date']}** — {h['part']} ({h['action']}) by {h['technician']}: _{h['notes']}_"
        for h in history[:5]
    ) or "_No history found._"

    description = f"""## Predictive Maintenance Alert

**Machine ID:** `{machine_id}`  
**Facility:** {facility}  
**Sensor:** {sensor_type}  
**Severity:** {severity}  
**Anomaly Score:** {anomaly_score:.3f}  
**Average Reading:** {avg_value:.3f} {unit}  
**Detected At:** {detected_at}  

### Recommended Action
Inspect the {sensor_type} system on **{machine_id}**.  
Assign to **{technician}**.  
{notes}

### Recent Part History
{history_md}

---
*Generated automatically by Confluent + WatsonX Orchestrate predictive maintenance pipeline.*
"""

    issue = _create_linear_issue(title, description, machine_id, severity)

    result = {
        "work_order":    issue,
        "notified":      technician,
        "machine_id":    machine_id,
        "sensor_type":   sensor_type,
        "severity":      severity,
        "anomaly_score": anomaly_score,
        "created_at":    datetime.now(timezone.utc).isoformat(),
    }

    # Store in in-memory registry so get_work_orders can return it
    _WORK_ORDERS[issue["id"]] = {
        "id":          issue["id"],
        "url":         issue.get("url", ""),
        "machine_id":  machine_id,
        "sensor_type": sensor_type,
        "severity":    severity,
        "notified":    technician,
        "created_at":  result["created_at"],
        "mock":        issue.get("mock", False),
    }

    return json.dumps(result, indent=2)


def tool_get_machine_status(arguments: dict) -> str:
    """Compute a health score for a machine from its most recent sensor readings."""
    machine_id = arguments.get("machine_id", "").lower().strip()
    if not machine_id:
        return json.dumps({"error": "machine_id is required"})

    # Pull the last 20 messages and filter to this machine
    messages = _read_last_n(TOPIC_SENSORS, 60)
    machine_msgs = [
        m for m in messages
        if isinstance(m.get("value"), dict)
        and m["value"].get("machine_id") == machine_id
    ]

    if not machine_msgs:
        return json.dumps({
            "machine_id":   machine_id,
            "health":       "unknown",
            "health_score": None,
            "reason":       "No recent sensor data found",
            "sensors":      {},
        })

    baselines = SENSOR_BASELINES.get(machine_id, {})
    sensor_results: dict[str, dict] = {}
    worst = "normal"

    for m in machine_msgs:
        v      = m["value"]
        stype  = v.get("sensor_type", "")
        value  = float(v.get("value", 0))
        unit   = v.get("unit", "")
        bl     = baselines.get(stype)

        if bl:
            ratio = value / bl["base"] if bl["base"] != 0 else 1.0
            if ratio >= bl["crit"] or ratio <= (1 / bl["crit"]):
                status = "critical"
            elif ratio >= bl["warn"] or ratio <= (1 / bl["warn"]):
                status = "warning"
            else:
                status = "normal"
        else:
            status = "unknown"

        # keep latest reading per sensor type
        if stype not in sensor_results or True:
            sensor_results[stype] = {
                "value":  round(value, 3),
                "unit":   unit,
                "status": status,
            }

        if status == "critical":
            worst = "critical"
        elif status == "warning" and worst != "critical":
            worst = "warning"

    score_map = {"normal": 100, "warning": 60, "critical": 20, "unknown": 50}
    scores    = [score_map.get(s["status"], 50) for s in sensor_results.values()]
    health_score = round(sum(scores) / len(scores)) if scores else 50

    return json.dumps({
        "machine_id":    machine_id,
        "health":        worst,
        "health_score":  health_score,
        "sensors":       sensor_results,
        "technician":    TECHNICIAN_MAP.get(machine_id, "maintenance@example.com"),
    }, indent=2)


def tool_list_active_anomalies(arguments: dict) -> str:
    """Return de-duplicated anomalies seen within the last max_age_minutes."""
    max_age  = int(arguments.get("max_age_minutes", 30))
    limit    = int(arguments.get("limit", 50))
    messages = _read_last_n(TOPIC_ALERTS, limit)
    cutoff   = datetime.now(timezone.utc) - timedelta(minutes=max_age)

    seen: dict[str, dict] = {}   # key: machine_id:sensor_type → latest record

    for m in messages:
        v = m.get("value", {})
        if not isinstance(v, dict):
            continue
        detected_str = v.get("detected_at", "")
        try:
            detected = datetime.fromisoformat(detected_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if detected < cutoff:
            continue
        key = f"{v.get('machine_id','')}:{v.get('sensor_type','')}"
        if key not in seen or detected > datetime.fromisoformat(
            seen[key]["detected_at"].replace("Z", "+00:00")
        ):
            seen[key] = v

    active = sorted(seen.values(), key=lambda x: x.get("severity",""), reverse=True)
    return json.dumps({
        "active_count":    len(active),
        "max_age_minutes": max_age,
        "anomalies":       active,
    }, indent=2)


def tool_acknowledge_alert(arguments: dict) -> str:
    """Write an acknowledgement record to alert-acknowledgements topic."""
    machine_id  = arguments.get("machine_id", "")
    sensor_type = arguments.get("sensor_type", "")
    ack_by      = arguments.get("acknowledged_by", "agent")
    notes       = arguments.get("notes", "")

    if not machine_id or not sensor_type:
        return json.dumps({"error": "machine_id and sensor_type are required"})

    record = {
        "machine_id":       machine_id,
        "sensor_type":      sensor_type,
        "acknowledged_by":  ack_by,
        "acknowledged_at":  datetime.now(timezone.utc).isoformat(),
        "notes":            notes,
    }
    try:
        _produce_one(TOPIC_ACKS, f"{machine_id}:{sensor_type}", record)
        status = "written"
    except Exception as exc:
        status = f"error: {exc}"

    return json.dumps({"status": status, "acknowledgement": record}, indent=2)


def tool_get_work_orders(arguments: dict) -> str:
    """List open work orders, optionally filtered by machine_id or severity."""
    machine_id = arguments.get("machine_id", "").lower().strip()
    severity   = arguments.get("severity", "").lower().strip()
    limit      = int(arguments.get("limit", 20))

    orders = list(_WORK_ORDERS.values())

    if machine_id:
        orders = [o for o in orders if o.get("machine_id") == machine_id]
    if severity:
        orders = [o for o in orders if o.get("severity") == severity]

    # Sort by created_at descending
    orders.sort(key=lambda o: o.get("created_at", ""), reverse=True)
    orders = orders[:limit]

    return json.dumps({
        "total":       len(orders),
        "work_orders": orders,
    }, indent=2)


def tool_check_parts_availability(arguments: dict) -> str:
    """Check inventory for parts compatible with a machine/sensor type."""
    machine_id  = arguments.get("machine_id", "").lower().strip()
    sensor_type = arguments.get("sensor_type", "").lower().strip()
    part_id     = arguments.get("part_id", "").upper().strip()

    if part_id:
        part = PARTS_CATALOG.get(part_id)
        if not part:
            return json.dumps({"error": f"Part '{part_id}' not found in catalog"})
        return json.dumps({"parts": [{**part, "part_id": part_id}]}, indent=2)

    candidate_ids: list[str] = []
    if sensor_type and sensor_type in SENSOR_PART_MAP:
        candidate_ids = SENSOR_PART_MAP[sensor_type]
    elif machine_id:
        candidate_ids = [pid for pid, p in PARTS_CATALOG.items() if machine_id in p["compatible"]]
    else:
        candidate_ids = list(PARTS_CATALOG.keys())

    parts = []
    for pid in candidate_ids:
        p = PARTS_CATALOG.get(pid)
        if not p:
            continue
        if machine_id and machine_id not in p["compatible"]:
            continue
        stock_status = (
            "in_stock"     if p["qty_on_hand"] > p["reorder_point"] else
            "low_stock"    if p["qty_on_hand"] > 0 else
            "out_of_stock"
        )
        parts.append({
            "part_id":      pid,
            "name":         p["name"],
            "qty_on_hand":  p["qty_on_hand"],
            "stock_status": stock_status,
            "unit_cost":    p["unit_cost"],
            "lead_days":    p["lead_days"],
            "supplier":     p["supplier"],
            "category":     p["category"],
        })

    return json.dumps({
        "machine_id":  machine_id or "all",
        "sensor_type": sensor_type or "all",
        "parts_count": len(parts),
        "parts":       parts,
    }, indent=2)


def tool_get_asset_info(arguments: dict) -> str:
    """Look up customer and asset registration details for a machine."""
    machine_id  = arguments.get("machine_id", "").lower().strip()
    customer_id = arguments.get("customer_id", "").upper().strip()

    if customer_id:
        customer = CUSTOMER_DB.get(customer_id)
        if not customer:
            return json.dumps({"error": f"Customer '{customer_id}' not found"})
        assets = [
            {**ASSET_REGISTRY[mid], "machine_id": mid}
            for mid in customer["assets"]
            if mid in ASSET_REGISTRY
        ]
        return json.dumps({"customer": customer, "assets": assets}, indent=2)

    if not machine_id:
        return json.dumps({"error": "machine_id or customer_id is required"})

    asset = ASSET_REGISTRY.get(machine_id)
    if not asset:
        return json.dumps({"error": f"No asset record for machine '{machine_id}'"})

    customer = CUSTOMER_DB.get(asset["customer_id"], {})

    from datetime import date
    today          = date.today().isoformat()
    warranty_status = "active" if asset["warranty_expiry"] > today else "expired"

    return json.dumps({
        "machine_id":      machine_id,
        "asset":           asset,
        "warranty_status": warranty_status,
        "customer":        customer,
        "sla_tier":        asset["sla_tier"],
        "sla_response_h":  asset["sla_response_h"],
    }, indent=2)


def tool_search_customers(arguments: dict) -> str:
    """Search customers by name, industry, or account manager."""
    query    = arguments.get("query", "").lower()
    industry = arguments.get("industry", "").lower()

    results = []
    for cid, c in CUSTOMER_DB.items():
        if query and query not in c["name"].lower() and query not in c.get("account_manager","").lower():
            continue
        if industry and industry not in c.get("industry","").lower():
            continue
        results.append({
            "customer_id":     cid,
            "name":            c["name"],
            "industry":        c["industry"],
            "account_manager": c["account_manager"],
            "am_email":        c["am_email"],
            "assets":          c["assets"],
            "asset_count":     len(c["assets"]),
            "contract_end":    c["contract_end"],
            "annual_value":    c["annual_value"],
        })

    return json.dumps({"count": len(results), "customers": results}, indent=2)


def tool_get_recommended_parts(arguments: dict) -> str:
    """Given a machine + sensor anomaly, recommend parts to order with availability and cost."""
    machine_id  = arguments.get("machine_id", "").lower().strip()
    sensor_type = arguments.get("sensor_type", "").lower().strip()
    severity    = arguments.get("severity", "warning").lower()

    candidate_ids = SENSOR_PART_MAP.get(sensor_type, [])
    asset         = ASSET_REGISTRY.get(machine_id, {})
    customer_name = asset.get("customer_name", "unknown")
    sla_h         = asset.get("sla_response_h", 24)

    recommendations = []
    total_cost      = 0.0

    for pid in candidate_ids:
        p = PARTS_CATALOG.get(pid)
        if not p:
            continue
        if machine_id and machine_id not in p["compatible"]:
            continue

        urgency = (
            "order_now"    if p["qty_on_hand"] == 0 else
            "stock_ok"     if p["qty_on_hand"] > p["reorder_point"] else
            "order_soon"
        )
        if severity == "critical" and p["qty_on_hand"] == 0:
            urgency = "urgent_order"

        recommendations.append({
            "part_id":      pid,
            "name":         p["name"],
            "qty_on_hand":  p["qty_on_hand"],
            "urgency":      urgency,
            "unit_cost":    p["unit_cost"],
            "lead_days":    p["lead_days"],
            "supplier":     p["supplier"],
            "can_meet_sla": p["lead_days"] * 24 <= sla_h or p["qty_on_hand"] > 0,
        })
        if urgency in ("order_now", "urgent_order"):
            total_cost += p["unit_cost"]

    return json.dumps({
        "machine_id":           machine_id,
        "sensor_type":          sensor_type,
        "severity":             severity,
        "customer":             customer_name,
        "sla_response_h":       sla_h,
        "recommendations":      recommendations,
        "estimated_parts_cost": round(total_cost, 2),
    }, indent=2)


def tool_produce_test_event(arguments: dict) -> str:
    """Inject a synthetic sensor reading into the sensor-readings topic."""
    machine_id  = arguments.get("machine_id", "turbine-1")
    sensor_type = arguments.get("sensor_type", "temperature")
    value       = float(arguments.get("value", 0.0))
    unit        = arguments.get("unit", "")
    facility    = arguments.get("facility", "plant-a")

    # Derive unit from baselines if not provided
    if not unit:
        unit_map = {
            "temperature": "celsius", "vibration": "mm/s", "pressure": "psi",
            "flow_rate": "L/min", "rpm": "rpm", "humidity": "percent",
        }
        unit = unit_map.get(sensor_type, "")

    record = {
        "facility":    facility,
        "machine_id":  machine_id,
        "sensor_type": sensor_type,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "unit":        unit,
        "value":       value,
    }
    try:
        _produce_one(TOPIC_SENSORS, f"{machine_id}:{sensor_type}", record)
        status = "produced"
    except Exception as exc:
        status = f"error: {exc}"

    return json.dumps({"status": status, "record": record}, indent=2)


# ── MCP tool registry ─────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name":        "kafka_read_alerts",
        "description": (
            "Read the latest equipment alert messages from the 'equipment-alerts' "
            "Kafka topic. Each alert was generated by Flink SQL anomaly detection "
            "and contains machine_id, sensor_type, anomaly_score, severity, and window stats."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of recent alerts to retrieve (default: 10, max: 50)",
                    "default": 10,
                },
            },
        },
        "fn": tool_kafka_read_alerts,
    },
    {
        "name":        "kafka_read_sensors",
        "description": (
            "Read the latest raw sensor readings from the 'sensor-readings' Kafka topic. "
            "Optionally filter to a specific machine_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of messages to retrieve (default: 10)",
                    "default": 10,
                },
                "machine_id": {
                    "type": "string",
                    "description": "Filter to a specific machine (e.g. 'turbine-1'). Leave empty for all.",
                },
            },
        },
        "fn": tool_kafka_read_sensors,
    },
    {
        "name":        "get_part_history",
        "description": (
            "Look up the maintenance and part-replacement history for a machine. "
            "Returns past repairs, calibrations, inspections, and the responsible technician."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "machine_id": {
                    "type": "string",
                    "description": "Machine identifier, e.g. 'turbine-1', 'compressor-1', 'pump-1', 'hvac-1'",
                },
            },
            "required": ["machine_id"],
        },
        "fn": tool_get_part_history,
    },
    {
        "name":        "create_work_order",
        "description": (
            "Create a work order (Linear issue) for a predictive maintenance alert. "
            "Automatically populates the issue with part history, assigns the responsible "
            "technician, and returns the issue URL."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "machine_id":    {"type": "string", "description": "Machine that triggered the alert"},
                "sensor_type":   {"type": "string", "description": "Sensor type (vibration, temperature, pressure, …)"},
                "severity":      {"type": "string", "enum": ["critical", "warning", "info"]},
                "anomaly_score": {"type": "number", "description": "Anomaly score from Flink (0.0 – 1.0)"},
                "avg_value":     {"type": "number", "description": "Average sensor reading during the anomaly window"},
                "unit":          {"type": "string", "description": "Unit of measurement"},
                "facility":      {"type": "string", "description": "Facility / plant name"},
                "detected_at":   {"type": "string", "description": "ISO 8601 timestamp of detection"},
                "notes":         {"type": "string", "description": "Additional notes for the work order"},
            },
            "required": ["machine_id", "sensor_type", "severity"],
        },
        "fn": tool_create_work_order,
    },
    {
        "name": "get_machine_status",
        "description": (
            "Compute a real-time health score (normal / warning / critical) for a machine "
            "by comparing its latest sensor readings against known baselines. "
            "Returns a per-sensor breakdown and an overall health score 0-100."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "machine_id": {"type": "string", "description": "e.g. turbine-1, compressor-1, pump-1, hvac-1"},
            },
            "required": ["machine_id"],
        },
        "fn": tool_get_machine_status,
    },
    {
        "name": "list_active_anomalies",
        "description": (
            "Return only currently-active equipment anomalies — de-duplicated by machine+sensor "
            "and filtered to those detected within the last max_age_minutes. "
            "Prevents the agent acting on stale alerts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_age_minutes": {"type": "integer", "description": "Only return anomalies detected within this window (default: 30)", "default": 30},
                "limit":           {"type": "integer", "description": "Max alerts to scan (default: 50)", "default": 50},
            },
        },
        "fn": tool_list_active_anomalies,
    },
    {
        "name": "acknowledge_alert",
        "description": (
            "Mark an equipment alert as acknowledged. Writes a record to the "
            "alert-acknowledgements Kafka topic so the dashboard and agent know "
            "the alert is being handled."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "machine_id":       {"type": "string"},
                "sensor_type":      {"type": "string"},
                "acknowledged_by":  {"type": "string", "description": "Name or email of acknowledger (default: agent)", "default": "agent"},
                "notes":            {"type": "string", "description": "Optional acknowledgement notes"},
            },
            "required": ["machine_id", "sensor_type"],
        },
        "fn": tool_acknowledge_alert,
    },
    {
        "name": "get_work_orders",
        "description": (
            "List open maintenance work orders, optionally filtered by machine_id or severity. "
            "Use this before create_work_order to avoid creating duplicates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "machine_id": {"type": "string", "description": "Filter to a specific machine (optional)"},
                "severity":   {"type": "string", "enum": ["critical", "warning", "info"], "description": "Filter by severity (optional)"},
                "limit":      {"type": "integer", "description": "Max results (default: 20)", "default": 20},
            },
        },
        "fn": tool_get_work_orders,
    },
    {
        "name": "produce_test_event",
        "description": (
            "Inject a synthetic sensor reading directly into the sensor-readings Kafka topic. "
            "Use this to simulate anomalies for testing without running sensor_producer.py."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "machine_id":  {"type": "string", "description": "Target machine (default: turbine-1)", "default": "turbine-1"},
                "sensor_type": {"type": "string", "description": "Sensor type", "default": "temperature"},
                "value":       {"type": "number", "description": "Sensor reading value"},
                "unit":        {"type": "string", "description": "Unit of measurement (inferred if omitted)"},
                "facility":    {"type": "string", "description": "Facility name (default: plant-a)", "default": "plant-a"},
            },
            "required": ["value"],
        },
        "fn": tool_produce_test_event,
    },
    # ── Inventory / Parts system ──────────────────────────────────────────────
    {
        "name": "check_parts_availability",
        "description": (
            "Query the parts & inventory system for stock levels, lead times, "
            "and supplier info. Filter by machine_id, sensor_type, or a specific part_id. "
            "System: Parts & Inventory (ERP/Warehouse)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "machine_id":  {"type": "string", "description": "Filter parts compatible with this machine"},
                "sensor_type": {"type": "string", "description": "Filter parts relevant to this sensor type"},
                "part_id":     {"type": "string", "description": "Specific part number, e.g. BRG-4821"},
            },
        },
        "fn": tool_check_parts_availability,
    },
    {
        "name": "get_recommended_parts",
        "description": (
            "Given a machine and sensor anomaly, recommend which parts to order, "
            "with stock status, lead time, supplier, and whether they can meet the customer SLA. "
            "System: Parts & Inventory + Customer Asset Registry."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "machine_id":  {"type": "string"},
                "sensor_type": {"type": "string"},
                "severity":    {"type": "string", "enum": ["critical", "warning", "info"], "default": "warning"},
            },
            "required": ["machine_id", "sensor_type"],
        },
        "fn": tool_get_recommended_parts,
    },
    # ── Customer & Asset Registry ─────────────────────────────────────────────
    {
        "name": "get_asset_info",
        "description": (
            "Look up the customer, warranty status, SLA tier, model, and serial number "
            "for a machine asset. Can also return all assets for a customer_id. "
            "System: Customer & Asset Registry (CRM/EAM)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "machine_id":  {"type": "string", "description": "e.g. turbine-1"},
                "customer_id": {"type": "string", "description": "e.g. CUST-1001 (alternative to machine_id)"},
            },
        },
        "fn": tool_get_asset_info,
    },
    {
        "name": "search_customers",
        "description": (
            "Search the customer registry by name, industry, or account manager. "
            "Returns customer details, assets owned, contract dates, and annual value. "
            "System: Customer & Asset Registry (CRM)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":    {"type": "string", "description": "Search term (name or account manager)"},
                "industry": {"type": "string", "description": "Filter by industry, e.g. 'energy', 'chemical'"},
            },
        },
        "fn": tool_search_customers,
    },
]

_TOOL_MAP: dict[str, dict] = {t["name"]: t for t in TOOLS}


# ── MCP server (FastMCP) ──────────────────────────────────────────────────────

mcp = FastMCP("confluent-predictive-maintenance")


@mcp.tool(description=TOOLS[0]["description"])
def kafka_read_alerts(limit: int = 10) -> str:
    return tool_kafka_read_alerts({"limit": limit})


@mcp.tool(description=TOOLS[1]["description"])
def kafka_read_sensors(limit: int = 10, machine_id: str = "") -> str:
    return tool_kafka_read_sensors({"limit": limit, "machine_id": machine_id})


@mcp.tool(description=TOOLS[2]["description"])
def get_part_history(machine_id: str) -> str:
    return tool_get_part_history({"machine_id": machine_id})


@mcp.tool(description=TOOLS[3]["description"])
def create_work_order(
    machine_id: str,
    sensor_type: str,
    severity: str,
    anomaly_score: float = 0.0,
    avg_value: float = 0.0,
    unit: str = "",
    facility: str = "unknown",
    detected_at: str = "",
    notes: str = "",
) -> str:
    return tool_create_work_order({
        "machine_id":    machine_id,
        "sensor_type":   sensor_type,
        "severity":      severity,
        "anomaly_score": anomaly_score,
        "avg_value":     avg_value,
        "unit":          unit,
        "facility":      facility,
        "detected_at":   detected_at,
        "notes":         notes,
    })


@mcp.tool(description=TOOLS[4]["description"])
def get_machine_status(machine_id: str) -> str:
    return tool_get_machine_status({"machine_id": machine_id})


@mcp.tool(description=TOOLS[5]["description"])
def list_active_anomalies(max_age_minutes: int = 30, limit: int = 50) -> str:
    return tool_list_active_anomalies({"max_age_minutes": max_age_minutes, "limit": limit})


@mcp.tool(description=TOOLS[6]["description"])
def acknowledge_alert(machine_id: str, sensor_type: str, acknowledged_by: str = "agent", notes: str = "") -> str:
    return tool_acknowledge_alert({
        "machine_id": machine_id, "sensor_type": sensor_type,
        "acknowledged_by": acknowledged_by, "notes": notes,
    })


@mcp.tool(description=TOOLS[7]["description"])
def get_work_orders(machine_id: str = "", severity: str = "", limit: int = 20) -> str:
    return tool_get_work_orders({"machine_id": machine_id, "severity": severity, "limit": limit})


@mcp.tool(description=TOOLS[8]["description"])
def produce_test_event(value: float, machine_id: str = "turbine-1", sensor_type: str = "temperature", unit: str = "", facility: str = "plant-a") -> str:
    return tool_produce_test_event({
        "machine_id": machine_id, "sensor_type": sensor_type,
        "value": value, "unit": unit, "facility": facility,
    })


@mcp.tool(description=TOOLS[9]["description"])
def check_parts_availability(machine_id: str = "", sensor_type: str = "", part_id: str = "") -> str:
    return tool_check_parts_availability({"machine_id": machine_id, "sensor_type": sensor_type, "part_id": part_id})


@mcp.tool(description=TOOLS[10]["description"])
def get_recommended_parts(machine_id: str, sensor_type: str, severity: str = "warning") -> str:
    return tool_get_recommended_parts({"machine_id": machine_id, "sensor_type": sensor_type, "severity": severity})


@mcp.tool(description=TOOLS[11]["description"])
def get_asset_info(machine_id: str = "", customer_id: str = "") -> str:
    return tool_get_asset_info({"machine_id": machine_id, "customer_id": customer_id})


@mcp.tool(description=TOOLS[12]["description"])
def search_customers(query: str = "", industry: str = "") -> str:
    return tool_search_customers({"query": query, "industry": industry})


# ── CLI entry point (also used for quick testing) ─────────────────────────────

def _cli_test(tool_name: str, args_json: str) -> None:
    """Quick local test: python3 mcp_server/server.py --test get_part_history '{"machine_id":"turbine-1"}'"""
    tool_def = _TOOL_MAP.get(tool_name)
    if not tool_def:
        print(f"Unknown tool '{tool_name}'. Available: {list(_TOOL_MAP)}")
        sys.exit(1)
    arguments = json.loads(args_json) if args_json.strip() else {}
    print(tool_def["fn"](arguments))


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Confluent Predictive Maintenance MCP Server")
    p.add_argument(
        "--test",
        nargs=2,
        metavar=("TOOL_NAME", "ARGS_JSON"),
        help="Test a tool locally: --test get_part_history '{\"machine_id\":\"turbine-1\"}'",
    )
    args = p.parse_args()

    if args.test:
        _cli_test(args.test[0], args.test[1])
    else:
        mcp.run()
