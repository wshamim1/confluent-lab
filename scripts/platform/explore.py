"""
explore.py — Interactive REST explorer for the on-prem Confluent Platform.

Covers lab step 45: Schema Registry, ksqlDB, Kafka Connect, CMF (Flink), brokers.

Usage:
    python3 explore.py                    # interactive menu
    python3 explore.py sr                 # Schema Registry subjects
    python3 explore.py ksql               # ksqlDB server info + streams/tables
    python3 explore.py connect            # Kafka Connect connectors + plugins
    python3 explore.py cmf                # CMF environments + compute pools
    python3 explore.py brokers            # Kafka broker metadata + topics
"""

import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from confluent_kafka import Consumer, KafkaException
from dotenv import load_dotenv

from auth import get_env, http_session, kafka_config

load_dotenv()

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(session, url: str, label: str) -> dict | list | None:
    """GET url, pretty-print result, return parsed JSON."""
    try:
        resp = session.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print(f"\n── {label} ──")
        print(json.dumps(data, indent=2))
        return data
    except Exception as error:
        print(f"[{label}] Error: {error}", file=sys.stderr)
        return None


def _post(session, url: str, payload: dict, label: str) -> dict | None:
    resp = session.post(url, json=payload, timeout=10,
                        headers={"Content-Type": "application/vnd.ksql.v1+json"})
    try:
        resp.raise_for_status()
        data = resp.json()
        print(f"\n── {label} ──")
        print(json.dumps(data, indent=2))
        return data
    except Exception as error:
        print(f"[{label}] Error {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
        return None


# ── Schema Registry (step 45 / section 6.1) ──────────────────────────────────

def explore_schema_registry():
    session, _ = http_session("SCHEMA_REGISTRY_URL")
    sr_url = os.getenv("SCHEMA_REGISTRY_URL", "").rstrip("/")

    subjects = _get(session, f"{sr_url}/subjects", "Registered subjects")
    if subjects:
        for subject in subjects[:5]:   # preview first 5
            _get(session, f"{sr_url}/subjects/{subject}/versions/latest",
                 f"Schema: {subject} (latest)")
        if len(subjects) > 5:
            print(f"\n  ... and {len(subjects) - 5} more subject(s).")


# ── ksqlDB (step 45 / section 6.2) ───────────────────────────────────────────

def explore_ksqldb():
    session, _ = http_session("KSQLDB_URL")
    ksql_url = os.getenv("KSQLDB_URL", "").rstrip("/")

    _get(session, f"{ksql_url}/info", "ksqlDB server info")

    for stmt in ["SHOW STREAMS;", "SHOW TABLES;", "SHOW QUERIES;"]:
        _post(session, f"{ksql_url}/ksql",
              {"ksql": stmt, "streamsProperties": {}},
              f"ksqlDB: {stmt}")


# ── Kafka Connect (step 45 / section 6.3) ────────────────────────────────────

def explore_connect():
    session, _ = http_session("KAFKA_CONNECT_URL")
    connect_url = os.getenv("KAFKA_CONNECT_URL", "").rstrip("/")

    connectors = _get(session, f"{connect_url}/connectors?expand=status",
                      "Deployed connectors")
    _get(session, f"{connect_url}/connector-plugins",
         "Installed connector plugins")

    # Show status for each deployed connector
    if isinstance(connectors, dict):
        for name, info in connectors.items():
            state = info.get("status", {}).get("connector", {}).get("state", "?")
            print(f"  {name}: {state}")


# ── CMF / Flink (step 45 / section 6.4) ──────────────────────────────────────

def explore_cmf():
    session, _ = http_session("CMF_REST_URL")
    cmf_url = os.getenv("CMF_REST_URL", "").rstrip("/")
    flink_env = os.getenv("FLINK_ENVIRONMENT", "flink-env")

    envs = _get(session, f"{cmf_url}/api/v1/environments", "Flink environments")
    _get(session, f"{cmf_url}/api/v1/environments/{flink_env}/compute-pools",
         f"Compute pools in '{flink_env}'")

    print(f"\n── Flink SQL shell command ──")
    cc_user = os.getenv("CONTROL_CENTER_USERNAME", "admin")
    cc_pass = os.getenv("CONTROL_CENTER_PASSWORD", "")
    vm_ip   = os.getenv("VM_FLOATING_IP", "<YOUR_VM_IP>")
    print(f"  confluent logout")
    print(f"  confluent flink shell \\")
    print(f"    --url https://{cc_user}:{cc_pass}@{vm_ip} \\")
    print(f"    --environment {flink_env} \\")
    print(f"    --compute-pool {os.getenv('FLINK_COMPUTE_POOL', 'flink-compute-pool')} \\")
    print(f"    --catalog {os.getenv('FLINK_CATALOG', 'flink-catalog')} \\")
    print(f"    --database {os.getenv('FLINK_DATABASE', 'flink-database')}")


# ── Kafka brokers (step 45 / section 6.5) ────────────────────────────────────

def explore_brokers():
    consumer = Consumer(kafka_config(
        client_id="explore-client",
        group_id="explore-client",
    ))
    try:
        metadata = consumer.list_topics(timeout=20)
        print(f"\n── Broker metadata ──")
        print(f"  Brokers : {len(metadata.brokers)}")
        for bid, broker in metadata.brokers.items():
            print(f"    [{bid}] {broker.host}:{broker.port}")

        topics = sorted(
            name for name in metadata.topics
            if not name.startswith("_")
        )
        print(f"\n  User topics ({len(topics)}):")
        if topics:
            for name in topics:
                t = metadata.topics[name]
                print(f"    - {name} (partitions={len(t.partitions)})")
        else:
            print("    (none yet — deploy a datagen connector to create topics)")
            print("    Run: ./setup-datagen.sh users")
    except KafkaException as error:
        print(f"Kafka error: {error}", file=sys.stderr)
        sys.exit(1)
    finally:
        consumer.close()


# ── Menu ──────────────────────────────────────────────────────────────────────

COMMANDS = {
    "sr":      ("Schema Registry subjects + schemas",  explore_schema_registry),
    "ksql":    ("ksqlDB server info, streams, tables",  explore_ksqldb),
    "connect": ("Kafka Connect connectors + plugins",   explore_connect),
    "cmf":     ("CMF Flink environments + compute pools", explore_cmf),
    "brokers": ("Kafka broker metadata + topics",       explore_brokers),
}


def interactive_menu():
    print("\nConfluent Platform Explorer")
    print("=" * 40)
    for key, (desc, _) in COMMANDS.items():
        print(f"  {key:<10} {desc}")
    print("  all        Run all of the above")
    print("  quit       Exit")
    print()
    choice = input("Select: ").strip().lower()
    return choice


if __name__ == "__main__":
    if get_env() != "onprem":
        sys.exit("explore.py only works with KAFKA_ENV=onprem")

    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else None

    if cmd is None:
        cmd = interactive_menu()

    if cmd in ("quit", "q", "exit"):
        sys.exit(0)
    elif cmd == "all":
        for key, (_, fn) in COMMANDS.items():
            print(f"\n{'='*50}\n{key.upper()}\n{'='*50}")
            fn()
    elif cmd in COMMANDS:
        COMMANDS[cmd][1]()
    else:
        print(f"Unknown command: '{cmd}'")
        print(f"Valid options: {', '.join(COMMANDS)} , all")
        sys.exit(1)
