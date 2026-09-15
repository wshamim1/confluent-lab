"""Health check for every Confluent Platform component.

Pings Kafka brokers (native protocol) plus all REST endpoints and reports
UP / DOWN with round-trip latency for each.  Exits with code 0 if everything
is up, 1 if any component is down.

Only meaningful with KAFKA_ENV=onprem (cloud has no REST components to probe).

Usage
-----
    KAFKA_ENV=onprem python3 scripts/platform/health_check.py

    # JSON output (useful for scripting / CI)
    KAFKA_ENV=onprem python3 scripts/platform/health_check.py --json

    # Fail fast — exit immediately on first failure
    KAFKA_ENV=onprem python3 scripts/platform/health_check.py --fail-fast
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from confluent_kafka import Consumer, KafkaException

from auth import get_env, http_session, kafka_config

# ── component definitions ──────────────────────────────────────────────────────
# Each entry: (display_name, env_key_for_url, probe_path, expected_http_status)
_HTTP_COMPONENTS = [
    ("Control Center",  "CONTROL_CENTER_URL",  "/",                      200),
    ("Schema Registry", "SCHEMA_REGISTRY_URL", "/subjects",              200),
    ("ksqlDB",          "KSQLDB_URL",          "/info",                  200),
    ("Kafka Connect",   "KAFKA_CONNECT_URL",   "/connectors",            200),
    ("CMF REST",        "CMF_REST_URL",        "/api/v1/environments",   200),
]

_GREEN = "\033[32m"
_RED   = "\033[31m"
_RESET = "\033[0m"


def _check_kafka() -> dict:
    """Check native Kafka broker connectivity via Consumer.list_topics()."""
    bootstrap = os.getenv("VM_BOOTSTRAP_SERVERS", "unknown")
    start = time.monotonic()
    try:
        cfg = kafka_config(client_id="health-check-client",
                           group_id="health-check-client")
        consumer = Consumer(cfg)
        meta = consumer.list_topics(timeout=10)
        consumer.close()
        latency_ms = round((time.monotonic() - start) * 1000)
        return {
            "name":       "Kafka brokers",
            "target":     bootstrap,
            "status":     "UP",
            "latency_ms": latency_ms,
            "detail":     f"{len(meta.brokers)} broker(s), {len(meta.topics)} topic(s)",
        }
    except (KafkaException, Exception) as exc:
        latency_ms = round((time.monotonic() - start) * 1000)
        return {
            "name":       "Kafka brokers",
            "target":     bootstrap,
            "status":     "DOWN",
            "latency_ms": latency_ms,
            "detail":     str(exc),
        }


def _check_http(name: str, env_key: str, path: str, expected: int,
                session) -> dict:
    """Check a single REST endpoint."""
    base = os.getenv(env_key, "").rstrip("/")
    if not base:
        return {
            "name":       name,
            "target":     "(not configured)",
            "status":     "SKIP",
            "latency_ms": 0,
            "detail":     f"{env_key} not set in .env",
        }
    url = f"{base}{path}"
    start = time.monotonic()
    try:
        resp = session.get(url, timeout=10)
        latency_ms = round((time.monotonic() - start) * 1000)
        status = "UP" if resp.status_code == expected else "WARN"
        return {
            "name":       name,
            "target":     base,
            "status":     status,
            "latency_ms": latency_ms,
            "detail":     f"HTTP {resp.status_code}",
        }
    except Exception as exc:
        latency_ms = round((time.monotonic() - start) * 1000)
        return {
            "name":       name,
            "target":     base,
            "status":     "DOWN",
            "latency_ms": latency_ms,
            "detail":     str(exc),
        }


def _print_table(results: list[dict]) -> None:
    print(f"\n  {'COMPONENT':<22}  {'STATUS':<6}  {'LATENCY':>8}  {'TARGET / DETAIL'}")
    print(f"  {'-'*22}  {'-'*6}  {'-'*8}  {'-'*45}")
    for r in results:
        status = r["status"]
        if status == "UP":
            colour = _GREEN
        elif status in ("DOWN", "WARN"):
            colour = _RED
        else:
            colour = ""
        status_str = f"{colour}{status}{_RESET}" if colour else status
        lat = f"{r['latency_ms']} ms"
        target = r["target"]
        detail = r["detail"]
        print(f"  {r['name']:<22}  {status_str:<6}  {lat:>8}  {target}")
        if detail and detail not in target:
            print(f"  {'':22}  {'':6}  {'':8}  ↳ {detail}")


def run(output_json: bool, fail_fast: bool) -> int:
    results: list[dict] = []

    # 1. Kafka native
    r = _check_kafka()
    results.append(r)
    if fail_fast and r["status"] == "DOWN":
        _finish(results, output_json)
        return 1

    # 2. REST endpoints
    try:
        session, _ = http_session("CONTROL_CENTER_URL")
    except SystemExit:
        session = None

    for name, env_key, path, expected in _HTTP_COMPONENTS:
        if session is None:
            results.append({
                "name": name, "target": "(session unavailable)",
                "status": "SKIP", "latency_ms": 0,
                "detail": "CONTROL_CENTER_PASSWORD not set",
            })
            continue
        r = _check_http(name, env_key, path, expected, session)
        results.append(r)
        if fail_fast and r["status"] == "DOWN":
            _finish(results, output_json)
            return 1

    _finish(results, output_json)
    return 0 if all(r["status"] in ("UP", "SKIP") for r in results) else 1


def _finish(results: list[dict], output_json: bool) -> None:
    if output_json:
        print(json.dumps(results, indent=2))
        return

    env = get_env()
    print(f"\nConfluent Platform Health Check  [KAFKA_ENV={env}]")
    _print_table(results)

    up   = sum(1 for r in results if r["status"] == "UP")
    down = sum(1 for r in results if r["status"] == "DOWN")
    warn = sum(1 for r in results if r["status"] == "WARN")
    skip = sum(1 for r in results if r["status"] == "SKIP")
    total = len(results)

    print(f"\n  Summary: {up}/{total} UP"
          + (f"  {down} DOWN" if down else "")
          + (f"  {warn} WARN" if warn else "")
          + (f"  {skip} SKIP" if skip else ""))

    if down == 0 and warn == 0:
        print(f"\n  {_GREEN}✓ All components healthy{_RESET}")
    else:
        print(f"\n  {_RED}✗ Some components are unhealthy — see above{_RESET}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Health check for every Confluent Platform component.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--json",      action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--fail-fast", action="store_true",
                        help="Exit immediately on first failure")
    return parser.parse_args()


if __name__ == "__main__":
    if get_env() != "onprem":
        sys.exit("health_check.py only works with KAFKA_ENV=onprem")
    args = parse_args()
    sys.exit(run(output_json=args.json, fail_fast=args.fail_fast))
