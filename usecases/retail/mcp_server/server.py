"""
usecases/retail/mcp_server/server.py — MCP server for the Retail Analytics use case.

Exposes 7 tools:
  retail_top_shoppers        — Rank customers by total spend
  retail_inactive_customers  — Customers with no orders in last N days
  retail_high_returners      — Customers with return rate above threshold
  retail_category_breakdown  — Spend / order count by product category
  retail_customer_profile    — Full purchase + return history for one customer
  retail_recent_orders       — Latest N orders from the stream
  retail_send_reminder       — Simulate sending a re-engagement reminder

Run (stdio transport):
    KAFKA_ENV=onprem python3 usecases/retail/mcp_server/server.py
"""

import json
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

sys.path.insert(0, ".")
from auth import kafka_config
from confluent_kafka import Consumer, KafkaError, TopicPartition
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, "usecases/retail")
from topics import (
    CUSTOMERS, CUSTOMER_MAP, PRODUCTS, PRODUCT_MAP,
    TOPIC_ORDERS, TOPIC_RETURNS, TOPIC_BROWSE,
    INACTIVE_CUSTOMERS, HIGH_RETURNERS,
)

from mcp.server.mcpserver import MCPServer as FastMCP

# ── Kafka helpers ──────────────────────────────────────────────────────────────

def _read_topic(topic: str, limit: int = 1000) -> list[dict]:
    """Read up to `limit` messages from `topic` from the beginning."""
    cfg = kafka_config(
        client_id=f"retail-mcp-{uuid.uuid4().hex[:6]}",
        group_id=f"retail-mcp-{uuid.uuid4().hex[:8]}",
    )
    cfg["auto.offset.reset"]  = "earliest"
    cfg["enable.auto.commit"] = False
    cfg["session.timeout.ms"] = 10000
    c = Consumer(cfg)

    meta  = c.list_topics(topic, timeout=10)
    parts = [TopicPartition(topic, p)
             for p in meta.topics[topic].partitions.keys()]
    if not parts:
        c.close()
        return []
    c.assign(parts)

    msgs    = []
    empties = 0
    while len(msgs) < limit and empties < 6:
        msg = c.poll(1.0)
        if msg is None:
            empties += 1
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                break
            continue
        empties = 0
        try:
            msgs.append(json.loads(msg.value().decode("utf-8", errors="replace")))
        except Exception:
            pass
    c.close()
    return msgs


def _all_orders() -> list[dict]:
    return _read_topic(TOPIC_ORDERS, 2000)

def _all_returns() -> list[dict]:
    return _read_topic(TOPIC_RETURNS, 2000)


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP("retail-analytics-mcp")

TOOLS = [
    {"name": "retail_top_shoppers",       "description": "Rank customers by total spend. Returns top N customers with order count, total spend, avg basket size, and segment."},
    {"name": "retail_inactive_customers", "description": "Find customers who have not placed any order in the last N days. Returns customer details and days since last order — use to trigger re-engagement reminders."},
    {"name": "retail_high_returners",     "description": "Identify customers whose return rate (returns/orders) exceeds a threshold. Returns customer name, order count, return count, return rate %, and top return reasons."},
    {"name": "retail_category_breakdown", "description": "Show total spend and order count broken down by product category."},
    {"name": "retail_customer_profile",   "description": "Full purchase and return history for a specific customer_id. Returns orders, returns, spend, and return rate."},
    {"name": "retail_recent_orders",      "description": "Show the latest N orders from the retail-orders Kafka topic."},
    {"name": "retail_send_reminder",      "description": "Simulate sending a re-engagement email reminder to an inactive customer. Returns confirmation with customer email."},
]


# ── Tool implementations ───────────────────────────────────────────────────────

def tool_retail_top_shoppers(params: dict) -> str:
    top_n  = int(params.get("top_n", 10))
    orders = _all_orders()

    spend:  dict[str, float] = defaultdict(float)
    count:  dict[str, int]   = defaultdict(int)

    for o in orders:
        if o.get("status") == "completed":
            cid = o.get("customer_id", "")
            spend[cid] += float(o.get("total", 0))
            count[cid] += 1

    ranked = sorted(spend.items(), key=lambda x: x[1], reverse=True)[:top_n]
    result = []
    for cid, total in ranked:
        info = CUSTOMER_MAP.get(cid, {})
        n    = count[cid]
        result.append({
            "customer_id":   cid,
            "name":          info.get("name", cid),
            "segment":       info.get("segment", "unknown"),
            "total_spend":   round(total, 2),
            "order_count":   n,
            "avg_basket":    round(total / n, 2) if n else 0,
        })

    return json.dumps({"top_n": top_n, "shoppers": result})


def tool_retail_inactive_customers(params: dict) -> str:
    days   = int(params.get("days", 7))
    orders = _all_orders()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    last_order: dict[str, datetime] = {}
    for o in orders:
        cid = o.get("customer_id", "")
        try:
            ts = datetime.fromisoformat(o["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if cid not in last_order or ts > last_order[cid]:
            last_order[cid] = ts

    inactive = []
    for c in CUSTOMERS:
        cid = c["customer_id"]
        lo  = last_order.get(cid)
        if lo is None or lo < cutoff:
            days_since = (datetime.now(timezone.utc) - lo).days if lo else None
            inactive.append({
                "customer_id":  cid,
                "name":         c["name"],
                "email":        c["email"],
                "segment":      c["segment"],
                "last_order":   lo.isoformat() if lo else "never",
                "days_inactive": days_since if days_since is not None else "never ordered",
            })

    inactive.sort(key=lambda x: (x["last_order"] == "never", x.get("days_inactive") or 9999), reverse=True)
    return json.dumps({"inactive_days_threshold": days, "count": len(inactive), "customers": inactive})


def tool_retail_high_returners(params: dict) -> str:
    threshold = float(params.get("threshold", 0.3))
    orders  = _all_orders()
    returns = _all_returns()

    order_count:  dict[str, int]   = defaultdict(int)
    return_count: dict[str, int]   = defaultdict(int)
    return_reasons: dict[str, list] = defaultdict(list)

    for o in orders:
        if o.get("status") == "completed":
            order_count[o.get("customer_id", "")] += 1
    for r in returns:
        cid = r.get("customer_id", "")
        return_count[cid] += 1
        reason = r.get("reason", "")
        if reason:
            return_reasons[cid].append(reason)

    result = []
    for cid, rc in return_count.items():
        oc = order_count.get(cid, 0)
        rate = rc / oc if oc > 0 else 1.0
        if rate >= threshold:
            info = CUSTOMER_MAP.get(cid, {})
            # top 3 reasons
            reasons = return_reasons[cid]
            top_reasons = sorted(set(reasons), key=reasons.count, reverse=True)[:3]
            result.append({
                "customer_id":   cid,
                "name":          info.get("name", cid),
                "segment":       info.get("segment", "unknown"),
                "order_count":   oc,
                "return_count":  rc,
                "return_rate":   round(rate * 100, 1),
                "top_reasons":   top_reasons,
            })

    result.sort(key=lambda x: x["return_rate"], reverse=True)
    return json.dumps({"threshold_pct": threshold * 100, "count": len(result), "customers": result})


def tool_retail_category_breakdown(params: dict) -> str:
    orders = _all_orders()

    spend: dict[str, float] = defaultdict(float)
    count: dict[str, int]   = defaultdict(int)

    for o in orders:
        if o.get("status") == "completed":
            cat = o.get("category", "Unknown")
            spend[cat] += float(o.get("total", 0))
            count[cat] += int(o.get("quantity", 1))

    rows = [
        {"category": cat, "total_spend": round(spend[cat], 2), "items_sold": count[cat]}
        for cat in sorted(spend, key=lambda c: spend[c], reverse=True)
    ]
    return json.dumps({"categories": rows, "total_revenue": round(sum(spend.values()), 2)})


def tool_retail_customer_profile(params: dict) -> str:
    cid = params.get("customer_id", "").upper()
    if not cid:
        return json.dumps({"error": "customer_id is required"})

    info = CUSTOMER_MAP.get(cid)
    if not info:
        return json.dumps({"error": f"Unknown customer {cid}"})

    orders  = [o for o in _all_orders()  if o.get("customer_id") == cid]
    returns = [r for r in _all_returns() if r.get("customer_id") == cid]

    completed = [o for o in orders if o.get("status") == "completed"]
    total_spend = sum(float(o.get("total", 0)) for o in completed)
    return_rate = len(returns) / len(completed) * 100 if completed else 0

    return json.dumps({
        "customer_id":   cid,
        "name":          info["name"],
        "email":         info["email"],
        "segment":       info["segment"],
        "total_orders":  len(orders),
        "completed_orders": len(completed),
        "total_spend":   round(total_spend, 2),
        "total_returns": len(returns),
        "return_rate":   round(return_rate, 1),
        "recent_orders": sorted(orders, key=lambda o: o.get("ts",""), reverse=True)[:5],
        "recent_returns": sorted(returns, key=lambda r: r.get("ts",""), reverse=True)[:3],
    })


def tool_retail_recent_orders(params: dict) -> str:
    limit  = int(params.get("limit", 20))
    orders = _all_orders()
    orders.sort(key=lambda o: o.get("ts",""), reverse=True)
    return json.dumps({"count": len(orders), "orders": orders[:limit]})


def tool_retail_send_reminder(params: dict) -> str:
    cid = params.get("customer_id", "").upper()
    if not cid:
        return json.dumps({"error": "customer_id is required"})
    info = CUSTOMER_MAP.get(cid)
    if not info:
        return json.dumps({"error": f"Unknown customer {cid}"})

    return json.dumps({
        "status":      "sent",
        "customer_id": cid,
        "name":        info["name"],
        "email":       info["email"],
        "segment":     info["segment"],
        "message":     f"Re-engagement email sent to {info['email']} — subject: 'We miss you, {info['name'].split()[0]}!'",
        "sent_at":     datetime.now(timezone.utc).isoformat(),
    })


# ── MCP tool registrations ────────────────────────────────────────────────────

@mcp.tool(description=TOOLS[0]["description"])
def retail_top_shoppers(top_n: int = 10) -> str:
    return tool_retail_top_shoppers({"top_n": top_n})

@mcp.tool(description=TOOLS[1]["description"])
def retail_inactive_customers(days: int = 7) -> str:
    return tool_retail_inactive_customers({"days": days})

@mcp.tool(description=TOOLS[2]["description"])
def retail_high_returners(threshold: float = 0.3) -> str:
    return tool_retail_high_returners({"threshold": threshold})

@mcp.tool(description=TOOLS[3]["description"])
def retail_category_breakdown() -> str:
    return tool_retail_category_breakdown({})

@mcp.tool(description=TOOLS[4]["description"])
def retail_customer_profile(customer_id: str) -> str:
    return tool_retail_customer_profile({"customer_id": customer_id})

@mcp.tool(description=TOOLS[5]["description"])
def retail_recent_orders(limit: int = 20) -> str:
    return tool_retail_recent_orders({"limit": limit})

@mcp.tool(description=TOOLS[6]["description"])
def retail_send_reminder(customer_id: str) -> str:
    return tool_retail_send_reminder({"customer_id": customer_id})


if __name__ == "__main__":
    mcp.run()
