"""
webhook_receiver.py — HTTP webhook receiver for equipment-alerts from Confluent.

Receives POST requests from:
  • Confluent Cloud HTTP Sink Connector (cloud)
  • Confluent Platform HTTP Sink connector (on-prem)
  • An ngrok tunnel pointing at this server

Each incoming request carries a single equipment-alert JSON payload (or a batch).
The receiver validates the payload and hands it directly to the MaintenanceAgent
for immediate processing — creating work orders and logging activity.

Endpoints
---------
  POST /alerts          Receive one or many alert records
  GET  /health          Health check (returns 200 OK + stats)
  GET  /metrics         JSON metrics (alerts received, work orders created)

Usage
-----
    # Start the webhook server (default: port 8080)
    KAFKA_ENV=cloud python3 agent/webhook_receiver.py

    # Custom port
    KAFKA_ENV=cloud python3 agent/webhook_receiver.py --port 9000

    # Dry-run (process alerts but don't create real work orders)
    KAFKA_ENV=cloud python3 agent/webhook_receiver.py --dry-run

Environment variables
---------------------
    WEBHOOK_PORT          HTTP port (default: 8080)
    WEBHOOK_SECRET        Optional Bearer token / shared secret for auth
    KAFKA_ENV             cloud | onprem
    LINEAR_API_KEY        Optional
    LINEAR_TEAM_ID        Optional

Confluent HTTP Sink connector config snippet
--------------------------------------------
    "connector.class":             "HttpSink",
    "http.api.url":                "http://<ngrok-or-host>:8080/alerts",
    "request.method":              "POST",
    "headers":                     "Content-Type:application/json",
    "behavior.on.error":           "LOG",
    "batch.max.size":              "10",
    "confluent.topic.bootstrap.servers": "<bootstrap>",
"""

import argparse
import json
import os
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

sys.path.insert(0, ".")
sys.path.insert(0, "usecases/predictive_maintenance/agent")
sys.path.insert(0, "usecases/predictive_maintenance/mcp_server")

from dotenv import load_dotenv

load_dotenv()

# Import the agent after dotenv so env vars are loaded
from maintenance_agent import MaintenanceAgent

# ── Shared state ──────────────────────────────────────────────────────────────
_lock         = threading.Lock()
_stats: dict[str, Any] = {
    "started_at":      datetime.now(timezone.utc).isoformat(),
    "alerts_received": 0,
    "work_orders":     0,
    "errors":          0,
    "last_alert_at":   None,
}

# The agent instance — shared across requests (thread-safe for our use case
# because the Kafka producer inside is thread-safe and we serialize per alert)
_agent: MaintenanceAgent | None = None


def get_agent() -> MaintenanceAgent:
    global _agent
    if _agent is None:
        dry_run = os.getenv("WEBHOOK_DRY_RUN", "false").lower() == "true"
        _agent  = MaintenanceAgent(dry_run=dry_run)
    return _agent


# ── Payload normalisation ─────────────────────────────────────────────────────

def _normalise_alerts(raw: Any) -> list[dict]:
    """
    Accept several payload shapes that Confluent connectors may send:
      • Single record:  { ... }
      • Batch array:    [ {...}, {...} ]
      • Wrapped batch:  { "records": [ {...} ] }
      • Confluent Cloud HTTP Sink envelope:
          { "key": ..., "value": {...} }  (single)
          [ { "key": ..., "value": {...} } ]  (batch)
    Returns a flat list of alert dicts.
    """
    alerts: list[dict] = []

    if isinstance(raw, list):
        # Could be plain alert list or list of Confluent envelopes
        for item in raw:
            if isinstance(item, dict):
                value = item.get("value", item)
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except Exception:
                        value = item
                if isinstance(value, dict):
                    alerts.append(value)
    elif isinstance(raw, dict):
        # Wrapped batch
        if "records" in raw and isinstance(raw["records"], list):
            return _normalise_alerts(raw["records"])
        # Confluent envelope with a value key
        if "value" in raw:
            v = raw["value"]
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except Exception:
                    v = raw
            if isinstance(v, dict):
                alerts.append(v)
                return alerts
        # Plain alert object
        alerts.append(raw)

    return alerts


# ── HTTP handler ──────────────────────────────────────────────────────────────

class AlertHandler(BaseHTTPRequestHandler):
    """Single-threaded HTTP handler — adequate for our demo webhook throughput."""

    log_prefix = "[webhook]"

    # suppress default request-line logging (we do our own)
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _check_auth(self) -> bool:
        secret = os.getenv("WEBHOOK_SECRET", "")
        if not secret:
            return True
        auth_header = self.headers.get("Authorization", "")
        return auth_header in (f"Bearer {secret}", secret)

    # ── GET /health ────────────────────────────────────────────────────────
    def _handle_health(self) -> None:
        with _lock:
            stats = dict(_stats)
        self._send_json(200, {"status": "ok", **stats})

    # ── GET /metrics ───────────────────────────────────────────────────────
    def _handle_metrics(self) -> None:
        with _lock:
            stats = dict(_stats)
        self._send_json(200, stats)

    # ── POST /alerts ───────────────────────────────────────────────────────
    def _handle_alerts(self) -> None:
        if not self._check_auth():
            self._send_json(401, {"error": "Unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)

        try:
            raw = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            with _lock:
                _stats["errors"] += 1
            self._send_json(400, {"error": f"Invalid JSON: {exc}"})
            return

        alerts = _normalise_alerts(raw)

        if not alerts:
            self._send_json(200, {"processed": 0, "message": "No alert records found"})
            return

        results = []
        agent   = get_agent()
        ts      = datetime.now(timezone.utc).isoformat()

        for alert in alerts:
            print(
                f"{self.log_prefix} → {alert.get('machine_id','?')} "
                f"/ {alert.get('sensor_type','?')} "
                f"(score={alert.get('anomaly_score',0):.3f})"
            )
            try:
                result = agent.process_alert(alert)
                results.append(result)
                with _lock:
                    _stats["alerts_received"] += 1
                    _stats["last_alert_at"]   = ts
                    if result.get("action") == "work_order_created":
                        _stats["work_orders"] += 1
            except Exception as exc:
                print(f"{self.log_prefix} ✗ Error processing alert: {exc}", file=sys.stderr)
                results.append({"error": str(exc), "alert": alert})
                with _lock:
                    _stats["errors"] += 1

        agent.flush()
        self._send_json(200, {
            "processed": len(results),
            "results":   results,
            "timestamp": ts,
        })

    # ── Router ─────────────────────────────────────────────────────────────
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/health":
            self._handle_health()
        elif path == "/metrics":
            self._handle_metrics()
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        if path == "/alerts":
            self._handle_alerts()
        else:
            self._send_json(404, {"error": "Not found"})


# ── Server ─────────────────────────────────────────────────────────────────────

def run_server(port: int, dry_run: bool) -> None:
    os.environ["WEBHOOK_DRY_RUN"] = "true" if dry_run else "false"
    get_agent()  # eagerly init so first request is fast

    server = HTTPServer(("0.0.0.0", port), AlertHandler)

    print(
        f"\n[webhook] Predictive Maintenance Webhook Receiver\n"
        f"{'─'*50}\n"
        f"  Listening : http://0.0.0.0:{port}/alerts\n"
        f"  Health    : http://0.0.0.0:{port}/health\n"
        f"  Metrics   : http://0.0.0.0:{port}/metrics\n"
        f"  Dry-run   : {dry_run}\n"
        f"{'─'*50}\n"
        f"Configure your Confluent HTTP Sink connector to POST to:\n"
        f"  http://<your-ngrok-url>/alerts\n"
        f"{'─'*50}\n"
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[webhook] Shutting down …")
        server.shutdown()
        with _lock:
            print(
                f"[webhook] Stats:\n"
                f"  alerts received : {_stats['alerts_received']}\n"
                f"  work orders     : {_stats['work_orders']}\n"
                f"  errors          : {_stats['errors']}\n"
            )


# ── Entry point ───────────────────────────────────────────────────────────────

def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Equipment alerts webhook receiver")
    p.add_argument("--port",    type=int, default=int(os.getenv("WEBHOOK_PORT", "8080")))
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse()
    run_server(args.port, args.dry_run)
