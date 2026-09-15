"""
maintenance_agent.py — Streaming predictive maintenance agent.

Consumes equipment-alerts from Kafka in real time, uses the MCP tool functions
directly (no HTTP round-trip needed when running locally), and auto-creates
Linear work orders for every anomaly detected.

This agent can also be triggered manually by pasting a raw alert JSON,
exactly like the Watson X Orchestrate chat interface shown in the demo.

Usage
-----
    # Run the streaming agent (reads equipment-alerts topic continuously)
    KAFKA_ENV=cloud python3 agent/maintenance_agent.py

    # Trigger manually from a JSON alert (like pasting into Orchestrate chat)
    KAFKA_ENV=cloud python3 agent/maintenance_agent.py \\
        --trigger '{"machine_id":"turbine-1","sensor_type":"vibration","severity":"critical","anomaly_score":0.95,"avg_value":13.4,"unit":"mm/s","facility":"plant-a"}'

    # Dry-run: show what would be done but don't create work orders
    KAFKA_ENV=cloud python3 agent/maintenance_agent.py --dry-run

Environment variables (in .env):
    KAFKA_ENV                cloud | onprem
    CONFLUENT_CLOUD_API_KEY / CONFLUENT_CLOUD_API_SECRET
    LINEAR_API_KEY           Optional — omit for mock work orders
    LINEAR_TEAM_ID           Optional
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, ".")
from auth import kafka_config

# Import MCP tool functions directly (no SDK transport needed)
sys.path.insert(0, "usecases/predictive_maintenance/mcp_server")
from server import (
    tool_create_work_order,
    tool_get_part_history,
    tool_kafka_read_alerts,
)

from confluent_kafka import Consumer, KafkaError
from dotenv import load_dotenv

load_dotenv()

TOPIC_ALERTS    = "equipment-alerts"
TOPIC_ACTIVITY  = "agent-activity"   # agent writes its own audit trail here
MIN_SCORE       = float(os.getenv("AGENT_MIN_ANOMALY_SCORE", "0.7"))


# ── Agent reasoning steps ─────────────────────────────────────────────────────

class MaintenanceAgent:
    """
    Stateful streaming agent that processes equipment alerts.

    Reasoning loop per alert:
      1. Parse the incoming alert record
      2. Fetch part history for the machine  (get_part_history tool)
      3. Decide severity and whether to act
      4. If actionable: create a work order  (create_work_order tool)
      5. Log activity to the agent-activity topic
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run    = dry_run
        self._producer  = None   # lazy init

    # ── Internal producer (writes activity log) ────────────────────────────

    def _get_producer(self):
        if self._producer is None:
            from confluent_kafka import Producer
            cfg = kafka_config(client_id="maintenance-agent-producer")
            self._producer = Producer(cfg)
        return self._producer

    def _log_activity(self, event_type: str, payload: dict) -> None:
        """Write an audit event to the agent-activity topic."""
        record = {
            "event_type": event_type,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "payload":    payload,
        }
        try:
            prod = self._get_producer()
            prod.produce(
                TOPIC_ACTIVITY,
                value=json.dumps(record).encode(),
                callback=lambda err, _msg: (
                    print(f"  ✗ activity log error: {err}", file=sys.stderr) if err else None
                ),
            )
            prod.poll(0)
        except Exception as exc:
            print(f"  [warn] Could not write activity log: {exc}", file=sys.stderr)

    # ── Core reasoning ─────────────────────────────────────────────────────

    def process_alert(self, alert: dict) -> dict:
        """Process a single equipment alert end-to-end. Returns a summary dict."""
        machine_id    = alert.get("machine_id",   "unknown")
        sensor_type   = alert.get("sensor_type",  "unknown")
        severity      = alert.get("severity",     "warning")
        anomaly_score = float(alert.get("anomaly_score", 0.0))
        avg_value     = float(alert.get("avg_value",     0.0))
        unit          = alert.get("unit",          "")
        facility      = alert.get("facility",      "unknown")
        detected_at   = alert.get("detected_at", datetime.now(timezone.utc).isoformat())
        window_start  = alert.get("window_start", "")
        window_end    = alert.get("window_end",   "")

        print(
            f"\n{'─'*60}\n"
            f"[agent] Alert received\n"
            f"  machine    : {machine_id}\n"
            f"  sensor     : {sensor_type}\n"
            f"  severity   : {severity}\n"
            f"  score      : {anomaly_score:.3f}\n"
            f"  avg value  : {avg_value:.3f} {unit}\n"
            f"  facility   : {facility}\n"
            f"  detected at: {detected_at}\n"
        )

        # Step 1: Skip low-confidence anomalies
        if anomaly_score < MIN_SCORE:
            print(f"[agent] Score {anomaly_score:.3f} < threshold {MIN_SCORE} — skipping.")
            return {"action": "skipped", "reason": "below_threshold", "alert": alert}

        # Step 2: Fetch part history  ← get_part_history tool
        print(f"[agent] → Calling get_part_history({machine_id}) …")
        history_json = tool_get_part_history({"machine_id": machine_id})
        history_data = json.loads(history_json)

        technician   = history_data.get("responsible_technician", "maintenance@example.com")
        history      = history_data.get("history", [])
        recent_parts = [h["part"] for h in history[:3]]

        print(
            f"[agent]   → {len(history)} history records found  "
            f"| responsible: {technician}\n"
            f"[agent]   → recent parts: {', '.join(recent_parts) or 'none'}"
        )

        # Step 3: Build context-aware notes
        notes = _build_notes(sensor_type, severity, recent_parts, window_start, window_end)

        # Step 4: Create work order  ← create_work_order tool
        if self.dry_run:
            print(f"[agent] DRY-RUN — would create work order: {severity} {sensor_type} on {machine_id}")
            result = {
                "action":    "dry_run",
                "title":     f"[{severity.upper()}] {sensor_type} anomaly on {machine_id}",
                "assignee":  technician,
            }
        else:
            print(f"[agent] → Calling create_work_order …")
            wo_json = tool_create_work_order({
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
            wo_data = json.loads(wo_json)
            wo      = wo_data.get("work_order", {})
            print(
                f"[agent]   → Work order created: {wo.get('id')}\n"
                f"[agent]   → URL: {wo.get('url')}\n"
                f"[agent]   → Notified: {wo_data.get('notified')}"
            )
            result = {
                "action":       "work_order_created",
                "work_order_id": wo.get("id"),
                "url":          wo.get("url"),
                "notified":     wo_data.get("notified"),
                "machine_id":   machine_id,
                "sensor_type":  sensor_type,
                "severity":     severity,
                "anomaly_score": anomaly_score,
                "mock":         wo.get("mock", False),
            }

        # Step 5: Log activity
        self._log_activity("work_order_created" if not self.dry_run else "dry_run", result)
        return result

    def flush(self) -> None:
        if self._producer:
            self._producer.flush()


def _build_notes(sensor_type: str, severity: str, recent_parts: list[str], ws: str, we: str) -> str:
    """Generate contextual repair notes based on sensor type and history."""
    advice_map = {
        "vibration":   "Check bearing wear, shaft alignment, and balance.",
        "temperature": "Inspect cooling system, lubrication, and thermal insulation.",
        "pressure":    "Check valve integrity, seals, and piping for leaks.",
        "flow_rate":   "Inspect impeller, inlet strainer, and valve positions.",
        "rpm":         "Check drive belt/coupling, load conditions, and controller settings.",
        "humidity":    "Inspect seals, drainage, and dehumidification unit.",
    }
    advice = advice_map.get(sensor_type, "Perform general inspection.")
    window = f"Anomaly window: {ws} – {we}." if ws and we else ""
    history_note = (
        f"Recent parts on record: {', '.join(recent_parts)}."
        if recent_parts else ""
    )
    return f"{advice} {window} {history_note}".strip()


# ── Streaming consumer loop ───────────────────────────────────────────────────

def run_streaming(agent: MaintenanceAgent) -> None:
    cfg = kafka_config(
        client_id="maintenance-agent-consumer",
        group_id=f"maintenance-agent-{os.getenv('HOSTNAME','local')}",
    )
    cfg["auto.offset.reset"]    = "latest"
    cfg["enable.auto.commit"]   = True
    cfg["auto.commit.interval.ms"] = 5000

    consumer = Consumer(cfg)
    consumer.subscribe([TOPIC_ALERTS])

    print(f"[agent] Streaming from '{TOPIC_ALERTS}' — Ctrl-C to stop")
    processed = 0

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                print(f"[agent] Kafka error: {msg.error()}", file=sys.stderr)
                continue

            try:
                alert = json.loads(msg.value().decode("utf-8", errors="replace"))
            except Exception as exc:
                print(f"[agent] Could not parse message: {exc}", file=sys.stderr)
                continue

            agent.process_alert(alert)
            processed += 1

    except KeyboardInterrupt:
        print(f"\n[agent] Stopped — processed {processed} alerts.")
    finally:
        consumer.close()
        agent.flush()


# ── Manual trigger (paste JSON directly) ─────────────────────────────────────

def run_manual(alert_json: str, agent: MaintenanceAgent) -> None:
    try:
        alert = json.loads(alert_json)
    except json.JSONDecodeError as exc:
        print(f"[agent] Invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    result = agent.process_alert(alert)
    print(f"\n[agent] Result:\n{json.dumps(result, indent=2)}")
    agent.flush()


# ── Entry point ───────────────────────────────────────────────────────────────

def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Predictive maintenance streaming agent")
    p.add_argument(
        "--trigger",
        metavar="ALERT_JSON",
        help="Process a single alert JSON (skip Kafka, for manual testing)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate actions without creating real work orders",
    )
    p.add_argument(
        "--min-score",
        type=float,
        default=MIN_SCORE,
        help=f"Minimum anomaly score to act on (default: {MIN_SCORE})",
    )
    return p.parse_args()


if __name__ == "__main__":
    args  = _parse()
    agent = MaintenanceAgent(dry_run=args.dry_run)
    MIN_SCORE = args.min_score  # allow CLI override

    if args.trigger:
        run_manual(args.trigger, agent)
    else:
        run_streaming(agent)
