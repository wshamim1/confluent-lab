"""register_schema.py — Register an AVRO schema for a Kafka topic in Schema Registry.

Once registered, the topic becomes visible as a typed table in Flink's KafkaCatalog.

Usage
-----
# Register a schema defined inline as a JSON string
KAFKA_ENV=onprem python3 scripts/platform/register_schema.py \\
    --topic topic1 \\
    --fields '[{"name":"id","type":"long"},{"name":"name","type":"string"}]'

# Register a schema from a .avsc / .json file
KAFKA_ENV=onprem python3 scripts/platform/register_schema.py \\
    --topic topic1 \\
    --schema-file path/to/schema.avsc

# Check what is already registered for a topic
KAFKA_ENV=onprem python3 scripts/platform/register_schema.py \\
    --topic topic1 --show

# List all registered subjects
KAFKA_ENV=onprem python3 scripts/platform/register_schema.py --list
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from auth import get_env, http_session

# ── Helpers ────────────────────────────────────────────────────────────────────

def _sr_session():
    """Return (session, sr_base_url) for Schema Registry."""
    session, base = http_session("SCHEMA_REGISTRY_URL")
    return session, base.rstrip("/")


def _build_schema_json(topic: str, fields_json: str | None, schema_file: str | None) -> str:
    """Return the full AVRO schema JSON string from either --fields or --schema-file."""
    if schema_file:
        with open(schema_file) as fh:
            raw = fh.read().strip()
        # Validate it parses as JSON
        json.loads(raw)
        return raw

    if fields_json:
        fields = json.loads(fields_json)
        schema = {
            "type": "record",
            "name": topic,
            "fields": fields,
        }
        return json.dumps(schema)

    sys.exit("Provide either --fields or --schema-file.")


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_list(session, base: str):
    """List all subjects registered in Schema Registry."""
    resp = session.get(f"{base}/subjects")
    resp.raise_for_status()
    subjects = resp.json()
    if not subjects:
        print("No subjects registered yet.")
        return
    print(f"Registered subjects ({len(subjects)}):")
    for s in sorted(subjects):
        print(f"  {s}")


def cmd_show(session, base: str, topic: str):
    """Show the latest schema version for <topic>-value."""
    subject = f"{topic}-value"
    resp = session.get(f"{base}/subjects/{subject}/versions/latest")
    if resp.status_code == 404:
        print(f"No schema registered for subject '{subject}'.")
        return
    resp.raise_for_status()
    data = resp.json()
    print(f"Subject : {subject}")
    print(f"Version : {data.get('version')}")
    print(f"ID      : {data.get('id')}")
    print("Schema  :")
    print(json.dumps(json.loads(data["schema"]), indent=2))


def cmd_register(session, base: str, topic: str, schema_str: str):
    """POST the schema to Schema Registry under <topic>-value."""
    subject = f"{topic}-value"

    # Check if already registered
    check = session.get(f"{base}/subjects/{subject}/versions/latest")
    if check.status_code == 200:
        print(f"Subject '{subject}' already has a schema (version {check.json().get('version')}).")
        print("Use --show to inspect it, or delete the subject first to replace it.")
        return

    payload = {"schema": schema_str}
    resp = session.post(
        f"{base}/subjects/{subject}/versions",
        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
        json=payload,
    )
    resp.raise_for_status()
    schema_id = resp.json().get("id")
    print(f"✓ Schema registered for subject '{subject}' (schema id={schema_id}).")
    print()
    print("The topic is now visible as a typed table in Flink:")
    print(f"  SHOW TABLES;")
    print(f"  SELECT * FROM `{topic}` LIMIT 10;")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Register an AVRO schema in Schema Registry so a Kafka topic "
                    "becomes visible as a Flink table.",
    )
    parser.add_argument("--topic", help="Kafka topic name (registers as <topic>-value)")
    parser.add_argument(
        "--fields",
        metavar="JSON",
        help='AVRO fields array, e.g. \'[{"name":"id","type":"long"},{"name":"name","type":"string"}]\'',
    )
    parser.add_argument("--schema-file", metavar="PATH", help="Path to a .avsc / .json schema file")
    parser.add_argument("--show", action="store_true", help="Show the current schema for --topic")
    parser.add_argument("--list", action="store_true", help="List all registered subjects")
    args = parser.parse_args()

    get_env()  # exits early if KAFKA_ENV is not onprem
    session, base = _sr_session()

    if args.list:
        cmd_list(session, base)
        return

    if not args.topic:
        parser.error("--topic is required (unless using --list)")

    if args.show:
        cmd_show(session, base, args.topic)
        return

    schema_str = _build_schema_json(args.topic, args.fields, args.schema_file)
    cmd_register(session, base, args.topic, schema_str)


if __name__ == "__main__":
    main()
