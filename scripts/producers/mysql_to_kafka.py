"""
mysql_to_kafka.py — Read a local MySQL table and produce rows to a Kafka topic.

Each row is serialised as **Avro** using the Confluent Schema Registry wire
format, so Flink's KafkaCatalog can discover the topic as a typed table
automatically (no DDL needed).

Works with both KAFKA_ENV=cloud and KAFKA_ENV=onprem.

Usage
-----
# Full table → topic (topic name defaults to table name)
python3 mysql_to_kafka.py --table bookings

# Custom topic name
python3 mysql_to_kafka.py --table bookings --topic my-bookings

# Custom SELECT query
python3 mysql_to_kafka.py \
  --query "SELECT id, customer_name, amount FROM bookings WHERE status='NEW'" \
  --topic bookings-new --table-meta bookings

# Continuous tail mode — poll for new rows every N seconds (watermark column)
python3 mysql_to_kafka.py --table bookings --tail --interval 10 --watermark-col id

Required .env additions (see README)
-------------------------------------
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=kafkauser
MYSQL_PASSWORD=kafkapass
MYSQL_DATABASE=kafkadb

# On-prem Schema Registry (already in .env if KAFKA_ENV=onprem)
SCHEMA_REGISTRY_URL=https://163.66.88.209/sr/
CONTROL_CENTER_USERNAME=admin
CONTROL_CENTER_PASSWORD=<password>
"""

import argparse
import io
import json
import os
import struct
import sys
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from datetime import datetime, date, timedelta
from decimal import Decimal

import fastavro
import mysql.connector
import requests
import urllib3
from confluent_kafka import Producer
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()


# ── MySQL → Avro type mapping ──────────────────────────────────────────────────

def _mysql_type_to_avro(col_type: str) -> str:
    """Map a MySQL DATA_TYPE string to a plain (non-nullable) Avro primitive type.

    Uses non-nullable primitives to match the schema style expected by the
    Flink KafkaCatalog on this cluster (same convention as ksqlDB / datagen).
    """
    t = col_type.lower()
    if any(t.startswith(x) for x in ("int", "tinyint", "smallint", "mediumint", "bigint")):
        return "long"
    if any(t.startswith(x) for x in ("float", "double", "real")):
        return "double"
    if any(t.startswith(x) for x in ("decimal", "numeric")):
        return "double"
    if any(t.startswith(x) for x in ("char", "varchar", "text", "tinytext",
                                      "mediumtext", "longtext", "enum", "set")):
        return "string"
    if t.startswith("bool"):
        return "boolean"
    if t in ("date", "datetime", "timestamp", "time", "year"):
        return "string"   # ISO-8601 string — readable in Flink as STRING
    if t.startswith("blob") or t.startswith("binary") or t.startswith("varbinary"):
        return "bytes"
    return "string"   # safe fallback


def build_avro_schema(table: str, columns: list[tuple]) -> dict:
    """Return an Avro schema dict compatible with the Flink KafkaCatalog.

    Must use non-nullable primitive field types — this cluster's KafkaCatalog
    uses the same schema convention as the DatagenConnector (ksqlDB datagen),
    which registers bare primitives (e.g. "long", "string") not nullable unions.
    Nullable unions cause Flink to fail at schema-binding time with
    "Cannot retrieve table" even though the topic appears in SHOW TABLES.
    """
    namespace = "ksql"
    fields = [
        {"name": col_name, "type": _mysql_type_to_avro(col_type)}
        for col_name, col_type in columns
    ]
    return {
        "type": "record",
        "name": table,
        "namespace": namespace,
        "fields": fields,
        "connect.name": f"{namespace}.{table}",
    }


# ── Value coercion — make Python values Avro-safe ─────────────────────────────

def _coerce(value):
    """Convert a MySQL value to an Avro-compatible Python type.

    None is converted to a type-safe default because the schema uses non-nullable
    primitives (required by this cluster's Flink KafkaCatalog).
    """
    if value is None:
        return ""          # safe fallback for non-nullable string fields
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, int):
        return value       # MySQL INT → Avro long
    return value


def coerce_row(row: dict, columns: list[tuple]) -> dict:
    """Coerce a MySQL row dict to match the Avro schema field types.

    Supplies type-appropriate zero-values for NULL columns because the schema
    uses non-nullable primitives (required by this cluster's Flink KafkaCatalog).
    """
    type_map = {col_name: col_type.lower() for col_name, col_type in columns}
    result = {}
    for k, v in row.items():
        col_type = type_map.get(k, "varchar")
        avro_type = _mysql_type_to_avro(col_type)
        if v is None:
            if avro_type == "long":
                result[k] = 0
            elif avro_type == "double":
                result[k] = 0.0
            elif avro_type == "boolean":
                result[k] = False
            elif avro_type == "bytes":
                result[k] = b""
            else:
                result[k] = ""
        else:
            result[k] = _coerce(v)
    return result


# ── MySQL connection ───────────────────────────────────────────────────────────

def mysql_connect():
    host     = os.getenv("MYSQL_HOST", "127.0.0.1")
    port     = int(os.getenv("MYSQL_PORT", "3306"))
    user     = os.getenv("MYSQL_USER")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE")

    missing = [n for n, v in {"MYSQL_USER": user, "MYSQL_DATABASE": database}.items() if not v]
    if missing:
        sys.exit(f"Missing .env settings: {', '.join(missing)}")

    try:
        conn = mysql.connector.connect(
            host=host, port=port,
            user=user, password=password, database=database,
            connection_timeout=10,
        )
        print(f"  ✓ MySQL  {host}:{port}/{database}")
        return conn
    except mysql.connector.Error as err:
        sys.exit(f"MySQL connection error: {err}")


def get_column_metadata(conn, database: str, table: str) -> list[tuple]:
    """Return [(column_name, data_type), ...] from INFORMATION_SCHEMA."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COLUMN_NAME, DATA_TYPE "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
        "ORDER BY ORDINAL_POSITION",
        (database, table),
    )
    cols = cursor.fetchall()
    cursor.close()
    if not cols:
        sys.exit(f"Table '{table}' not found in database '{database}'")
    return cols


# ── Schema Registry — manual registration via requests (TLS-safe) ─────────────

def _sr_session() -> tuple[requests.Session, str]:
    """Return a (session, base_url) for Schema Registry using existing auth.py logic."""
    sr_url  = os.getenv("SCHEMA_REGISTRY_URL", "").rstrip("/")
    env     = os.getenv("KAFKA_ENV", "cloud").lower()
    sr_user = os.getenv("CONTROL_CENTER_USERNAME", "admin")
    sr_pass = os.getenv("CONTROL_CENTER_PASSWORD", "")

    if not sr_url:
        sys.exit("Missing SCHEMA_REGISTRY_URL in .env")

    session = requests.Session()

    if env == "onprem":
        if not sr_pass:
            sys.exit("Missing CONTROL_CENTER_PASSWORD in .env")
        session.auth   = (sr_user, sr_pass)
        session.verify = False   # VM uses a self-signed cert (same as explore.py)
    else:
        sr_key    = os.getenv("SCHEMA_REGISTRY_API_KEY", "")
        sr_secret = os.getenv("SCHEMA_REGISTRY_API_SECRET", "")
        if sr_key and sr_secret:
            session.auth = (sr_key, sr_secret)
        session.verify = True

    return session, sr_url


def register_schema(schema_dict: dict, subject: str) -> int:
    """Register an Avro schema under `subject` and return the schema ID."""
    session, sr_url = _sr_session()
    url     = f"{sr_url}/subjects/{subject}/versions"
    payload = {"schema": json.dumps(schema_dict), "schemaType": "AVRO"}

    resp = session.post(url, json=payload,
                        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
                        timeout=10)
    if resp.status_code not in (200, 201):
        sys.exit(f"Schema Registry registration failed ({resp.status_code}): {resp.text[:300]}")

    schema_id = resp.json()["id"]
    print(f"  ✓ Schema Registry  subject='{subject}'  id={schema_id}")
    return schema_id


# ── Avro encoding — Confluent wire format ─────────────────────────────────────
# Magic byte (0x00) + 4-byte big-endian schema ID + Avro binary payload

def encode_avro(row: dict, parsed_schema, schema_id: int) -> bytes:
    buf = io.BytesIO()
    buf.write(b"\x00")                        # magic byte
    buf.write(struct.pack(">I", schema_id))   # 4-byte schema ID
    fastavro.schemaless_writer(buf, parsed_schema, row)
    return buf.getvalue()


# ── Kafka producer ─────────────────────────────────────────────────────────────

def make_producer() -> Producer:
    from auth import kafka_config
    cfg = kafka_config(client_id="mysql-to-kafka")
    cfg.update({"acks": "all", "retries": 3, "retry.backoff.ms": 500,
                "delivery.timeout.ms": 15000,   # fail fast in lab
                "request.timeout.ms": 10000})
    return Producer(cfg)


def _delivery_report(err, msg):
    if err:
        print(f"  ✗ Delivery failed  key={msg.key()}  {err}", file=sys.stderr)


# ── Core: fetch rows and produce ──────────────────────────────────────────────

def fetch_and_produce(conn, producer, parsed_schema, schema_id: int,
                      sql: str, topic: str, key_col: str | None,
                      columns: list[tuple]) -> int:
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql)
    rows = cursor.fetchall()
    cursor.close()

    count = 0
    for row in rows:
        row   = coerce_row(row, columns)
        key   = str(row[key_col]).encode() if key_col and key_col in row else None
        value = encode_avro(row, parsed_schema, schema_id)
        producer.produce(topic, key=key, value=value, callback=_delivery_report)
        count += 1
        if count % 1000 == 0:
            producer.poll(0)

    producer.flush()
    return count


# ── Tail / CDC mode ───────────────────────────────────────────────────────────

def tail_mode(conn, producer, parsed_schema, schema_id: int,
              table: str, topic: str,
              watermark_col: str, key_col: str | None, interval: int,
              columns: list[tuple]):
    cursor = conn.cursor()
    cursor.execute(f"SELECT MAX(`{watermark_col}`) FROM `{table}`")
    (watermark,) = cursor.fetchone()
    cursor.close()

    print(f"  Tail mode — watermark col='{watermark_col}', initial value={watermark!r}")
    print(f"  Polling every {interval}s — Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(interval)
            conn.reconnect(attempts=3, delay=2)
            sql = (
                f"SELECT * FROM `{table}` "
                f"WHERE `{watermark_col}` > %s "
                f"ORDER BY `{watermark_col}` ASC"
            )
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, (watermark,))
            rows = cursor.fetchall()
            cursor.close()

            if rows:
                for row in rows:
                    row   = coerce_row(row, columns)
                    key   = str(row[key_col]).encode() if key_col and key_col in row else None
                    value = encode_avro(row, parsed_schema, schema_id)
                    producer.produce(topic, key=key, value=value, callback=_delivery_report)
                producer.flush()
                watermark = rows[-1][watermark_col]
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
                      f"Sent {len(rows)} row(s)  watermark={watermark!r}")
            else:
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] No new rows.")

    except KeyboardInterrupt:
        print("\n  Stopped.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Read a local MySQL table and produce Avro rows to a Kafka topic.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--table", help="MySQL table name to read")
    src.add_argument("--query", help="Custom SELECT SQL (requires --topic and --table-meta)")

    parser.add_argument("--topic",         help="Kafka topic name (defaults to table name)")
    parser.add_argument("--key-col",       help="Column to use as the Kafka message key")
    parser.add_argument("--tail",          action="store_true",
                        help="Continuous mode: poll for new rows")
    parser.add_argument("--watermark-col", default="id",
                        help="Column used as tail watermark (default: id)")
    parser.add_argument("--interval",      type=int, default=10,
                        help="Poll interval in seconds for --tail (default: 10)")
    parser.add_argument("--table-meta",
                        help="Table to read column metadata from when using --query")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.query and args.tail:
        sys.exit("--tail requires --table, not --query")

    topic = args.topic or args.table
    if not topic:
        sys.exit("Provide --topic when using --query")

    meta_table = args.table or args.table_meta
    if not meta_table:
        sys.exit("Provide --table-meta <table> so the Avro schema can be inferred when using --query")

    env = os.getenv("KAFKA_ENV", "cloud")
    print(f"\n── MySQL → Kafka (Avro)  [KAFKA_ENV={env}] ──")
    print(f"  Topic  : {topic}")

    conn     = mysql_connect()
    database = os.getenv("MYSQL_DATABASE", "")

    # 1. Infer Avro schema from MySQL column metadata
    columns    = get_column_metadata(conn, database, meta_table)
    schema_dict = build_avro_schema(meta_table, columns)
    print(f"  Schema : {len(columns)} field(s) inferred from '{meta_table}'")

    # 2. Register schema in Schema Registry → get schema ID
    subject   = f"{topic}-value"
    schema_id = register_schema(schema_dict, subject)

    # 3. Parse schema once for fastavro encoding
    parsed_schema = fastavro.parse_schema(schema_dict)

    # 4. Build Kafka producer
    producer = make_producer()

    if args.tail:
        tail_mode(conn, producer, parsed_schema, schema_id,
                  args.table, topic, args.watermark_col, args.key_col, args.interval,
                  columns)
    else:
        sql   = args.query or f"SELECT * FROM `{meta_table}`"
        print(f"  Query  : {sql}\n")
        count = fetch_and_produce(conn, producer, parsed_schema, schema_id,
                                  sql, topic, args.key_col, columns)
        print(f"\n  ✓ Sent {count} row(s) to topic '{topic}'.")
        print(f"  ✓ Schema registered as subject '{subject}' in Schema Registry.")
        print(f"\n  In Flink SQL:")
        print(f"    SHOW TABLES;")
        print(f"    SELECT * FROM `{topic}` LIMIT 10;")

    conn.close()


if __name__ == "__main__":
    main()
