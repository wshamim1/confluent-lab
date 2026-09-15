"""Run ksqlDB statements and queries from the CLI.

Supports both DDL/DML statements (CREATE, DROP, INSERT) and pull/push queries
(SELECT).  Push queries stream results until Ctrl-C or --limit is reached.

Only works with KAFKA_ENV=onprem.

Usage
-----
    # Run a DDL statement
    KAFKA_ENV=onprem python3 scripts/platform/ksql_query.py "SHOW STREAMS;"
    KAFKA_ENV=onprem python3 scripts/platform/ksql_query.py "SHOW TABLES;"
    KAFKA_ENV=onprem python3 scripts/platform/ksql_query.py "SHOW QUERIES;"

    # Pull query (returns immediately)
    KAFKA_ENV=onprem python3 scripts/platform/ksql_query.py "SELECT * FROM users_table WHERE id=1;"

    # Push query (streams rows — Ctrl-C to stop)
    KAFKA_ENV=onprem python3 scripts/platform/ksql_query.py "SELECT * FROM users EMIT CHANGES;" --limit 10

    # Create a stream
    KAFKA_ENV=onprem python3 scripts/platform/ksql_query.py \\
        "CREATE STREAM pageviews (viewtime BIGINT, userid VARCHAR, pageid VARCHAR) \\
         WITH (KAFKA_TOPIC='pageviews', VALUE_FORMAT='AVRO');"

    # Pass multiple statements from a file
    KAFKA_ENV=onprem python3 scripts/platform/ksql_query.py --file my_queries.sql
"""

import argparse
import json
import os
import signal
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests

from auth import get_env, http_session

_RUNNING = True


def _handle_sigint(sig, frame):   # noqa: ARG001
    global _RUNNING
    _RUNNING = False


# ── statement (DDL / DML / SHOW …) ────────────────────────────────────────────

def run_statement(session: requests.Session, ksql_url: str, sql: str) -> None:
    """POST to /ksql — handles DDL, DML, and SHOW/LIST statements."""
    payload = {"ksql": sql, "streamsProperties": {}}
    try:
        resp = session.post(
            f"{ksql_url}/ksql",
            json=payload,
            headers={"Content-Type": "application/vnd.ksql.v1+json"},
            timeout=30,
        )
    except Exception as exc:
        sys.exit(f"Request failed: {exc}")

    if resp.status_code not in (200, 201):
        try:
            err = resp.json()
            msg = err.get("message") or err.get("@type") or resp.text[:300]
        except Exception:
            msg = resp.text[:300]
        sys.exit(f"ksqlDB error (HTTP {resp.status_code}): {msg}")

    data = resp.json()
    if isinstance(data, list):
        for item in data:
            _print_statement_result(item)
    else:
        _print_statement_result(data)


def _print_statement_result(item: dict) -> None:
    """Pretty-print a single statement result object."""
    kind = item.get("@type", "")

    # SHOW STREAMS / TABLES / QUERIES
    for key in ("streams", "tables", "queries", "topics", "connectors",
                "sourceDescription", "queryDescription"):
        if key in item:
            rows = item[key]
            if not isinstance(rows, list):
                rows = [rows]
            if not rows:
                print(f"  (no {key})")
                return
            # Print as a simple table using the first item's keys as headers
            headers = list(rows[0].keys()) if rows else []
            if headers:
                widths = [max(len(str(r.get(h, ""))) for r in rows + [{}])
                          for h in headers]
                widths = [max(w, len(h)) for w, h in zip(widths, headers)]
                header_row = "  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths))
                sep = "  " + "  ".join("-" * w for w in widths)
                print(header_row)
                print(sep)
                for row in rows:
                    print("  " + "  ".join(
                        str(row.get(h, "")).ljust(w)
                        for h, w in zip(headers, widths)
                    ))
            else:
                print(json.dumps(rows, indent=2))
            return

    # Generic fallback
    print(json.dumps(item, indent=2))


# ── query (SELECT … EMIT CHANGES or pull query) ────────────────────────────────

def run_query(session: requests.Session, ksql_url: str,
              sql: str, limit: int | None) -> None:
    """POST to /query-stream (HTTP/1.1 streaming) and print rows."""
    payload = {"sql": sql, "properties": {}}
    try:
        resp = session.post(
            f"{ksql_url}/query-stream",
            json=payload,
            headers={
                "Content-Type":  "application/vnd.ksql.v1+json",
                "Accept":        "application/vnd.ksqlapi.delimited.v1",
            },
            stream=True,
            timeout=None,       # push queries run indefinitely
        )
    except Exception as exc:
        sys.exit(f"Request failed: {exc}")

    if resp.status_code not in (200, 201):
        try:
            msg = resp.json().get("message", resp.text[:300])
        except Exception:
            msg = resp.text[:300]
        sys.exit(f"ksqlDB error (HTTP {resp.status_code}): {msg}")

    signal.signal(signal.SIGINT, _handle_sigint)
    count = 0
    schema_printed = False

    try:
        for raw_line in resp.iter_lines():
            if not _RUNNING:
                break
            if not raw_line:
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError:
                print(raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line)
                continue

            # First row is the schema/header
            if not schema_printed:
                if "columnNames" in row:
                    cols = row["columnNames"]
                    print("  " + "  ".join(f"{c:<20}" for c in cols))
                    print("  " + "  ".join("-" * 20 for _ in cols))
                    schema_printed = True
                    continue
                else:
                    schema_printed = True  # no schema row

            # Data row — list of values
            if isinstance(row, list):
                print("  " + "  ".join(f"{str(v):<20}" for v in row))
                count += 1
            elif "finalMessage" in row:
                print(f"\n  {row['finalMessage']}")
                break
            else:
                print(json.dumps(row))
                count += 1

            if limit is not None and count >= limit:
                break
    finally:
        resp.close()

    print(f"\n  Rows received: {count}")


# ── helpers ────────────────────────────────────────────────────────────────────

def _is_select(sql: str) -> bool:
    return sql.strip().upper().startswith("SELECT")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ksqlDB statements and queries from the CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("sql", nargs="?", default=None,
                       help="SQL statement or query to run")
    group.add_argument("--file", metavar="PATH",
                       help="Path to a .sql file containing one or more statements")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop push query after N rows (default: stream until Ctrl-C)")
    return parser.parse_args()


if __name__ == "__main__":
    if get_env() != "onprem":
        sys.exit("ksql_query.py only works with KAFKA_ENV=onprem")

    args = parse_args()

    if args.file:
        with open(args.file) as fh:
            content = fh.read()
        # Split on semicolons, keeping each statement
        stmts = [s.strip() for s in content.split(";") if s.strip()]
    else:
        stmts = [args.sql]

    session, ksql_url = http_session("KSQLDB_URL")
    ksql_url = ksql_url.rstrip("/")

    for stmt in stmts:
        sql = stmt if stmt.endswith(";") else stmt + ";"
        print(f"\n▶ {sql}\n")
        if _is_select(sql):
            run_query(session, ksql_url, sql, args.limit)
        else:
            run_statement(session, ksql_url, sql)
