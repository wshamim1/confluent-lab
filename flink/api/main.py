"""
api/main.py — FastAPI service exposing PostgreSQL sensor aggregates and alerts.

Endpoints
---------
    GET /sensors          Latest 100 window aggregates (all machines)
    GET /sensors/{id}     Aggregates for a single machine
    GET /alerts           Latest 50 anomaly alerts
    GET /alerts/{id}      Alerts for a single machine
    GET /health           Liveness probe

Run
---
    pip install fastapi uvicorn psycopg2-binary
    uvicorn api.main:app --reload --port 8000

Or from the flink/ folder:
    uvicorn main:app --reload --port 8000
"""

import os
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ── Config ────────────────────────────────────────────────────────────────────

DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
DB_NAME = os.getenv("POSTGRES_DB",   "streaming")
DB_USER = os.getenv("POSTGRES_USER", "flink")
DB_PASS = os.getenv("POSTGRES_PASS", "flink")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Flink Pipeline API",
    description="Serves sensor aggregates and anomaly alerts from PostgreSQL",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── DB helpers ────────────────────────────────────────────────────────────────

@contextmanager
def get_conn() -> Generator:
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        dbname=DB_NAME, user=DB_USER, password=DB_PASS,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    try:
        yield conn
    finally:
        conn.close()


def _query(sql: str, params=None) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return [dict(row) for row in cur.fetchall()]


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    try:
        _query("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/sensors")
def get_sensor_aggregates(limit: int = 100):
    """Latest window aggregates across all machines, newest first."""
    rows = _query(
        """
        SELECT machine_id, sensor_type, facility,
               window_start, window_end,
               avg_value, min_value, max_value,
               event_count, unit, inserted_at
        FROM sensor_aggregates
        ORDER BY window_start DESC
        LIMIT %s
        """,
        (limit,),
    )
    return rows


@app.get("/sensors/{machine_id}")
def get_sensor_aggregates_for_machine(machine_id: str, limit: int = 100):
    """Window aggregates for a single machine."""
    rows = _query(
        """
        SELECT machine_id, sensor_type, facility,
               window_start, window_end,
               avg_value, min_value, max_value,
               event_count, unit, inserted_at
        FROM sensor_aggregates
        WHERE machine_id = %s
        ORDER BY window_start DESC
        LIMIT %s
        """,
        (machine_id, limit),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"No data for machine '{machine_id}'")
    return rows


@app.get("/alerts")
def get_alerts(limit: int = 50, severity: str = ""):
    """Latest anomaly alerts, optionally filtered by severity (warning | critical)."""
    if severity:
        rows = _query(
            """
            SELECT machine_id, sensor_type, facility,
                   window_start, window_end,
                   avg_value, min_value, max_value,
                   anomaly_score, severity, unit, detected_at
            FROM equipment_alerts
            WHERE severity = %s
            ORDER BY detected_at DESC
            LIMIT %s
            """,
            (severity, limit),
        )
    else:
        rows = _query(
            """
            SELECT machine_id, sensor_type, facility,
                   window_start, window_end,
                   avg_value, min_value, max_value,
                   anomaly_score, severity, unit, detected_at
            FROM equipment_alerts
            ORDER BY detected_at DESC
            LIMIT %s
            """,
            (limit,),
        )
    return rows


@app.get("/alerts/{machine_id}")
def get_alerts_for_machine(machine_id: str, limit: int = 50):
    """Anomaly alerts for a single machine."""
    rows = _query(
        """
        SELECT machine_id, sensor_type, facility,
               window_start, window_end,
               avg_value, min_value, max_value,
               anomaly_score, severity, unit, detected_at
        FROM equipment_alerts
        WHERE machine_id = %s
        ORDER BY detected_at DESC
        LIMIT %s
        """,
        (machine_id, limit),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"No alerts for machine '{machine_id}'")
    return rows


@app.get("/summary")
def get_summary():
    """Per-machine latest avg_value and alert count — useful for dashboard overview cards."""
    aggregates = _query(
        """
        SELECT DISTINCT ON (machine_id, sensor_type)
               machine_id, sensor_type, facility,
               avg_value, min_value, max_value, unit, window_start
        FROM sensor_aggregates
        ORDER BY machine_id, sensor_type, window_start DESC
        """
    )
    alert_counts = _query(
        """
        SELECT machine_id, COUNT(*) AS alert_count,
               MAX(severity) AS worst_severity
        FROM equipment_alerts
        WHERE detected_at > NOW() - INTERVAL '1 hour'
        GROUP BY machine_id
        """
    )
    counts_by_machine = {r["machine_id"]: r for r in alert_counts}

    for row in aggregates:
        machine = row["machine_id"]
        row["alert_count"]    = counts_by_machine.get(machine, {}).get("alert_count", 0)
        row["worst_severity"] = counts_by_machine.get(machine, {}).get("worst_severity", "normal")

    return aggregates
