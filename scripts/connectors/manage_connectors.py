"""Manage Kafka Connect connectors via the REST API.

List, describe, pause, resume, restart, and delete connectors.
Only works with KAFKA_ENV=onprem.

Usage
-----
    # List all deployed connectors with their state
    KAFKA_ENV=onprem python3 scripts/connectors/manage_connectors.py list

    # Describe a specific connector (config + task statuses)
    KAFKA_ENV=onprem python3 scripts/connectors/manage_connectors.py describe datagen-users-source

    # Show all available connector plugins installed on the cluster
    KAFKA_ENV=onprem python3 scripts/connectors/manage_connectors.py plugins

    # Pause a running connector
    KAFKA_ENV=onprem python3 scripts/connectors/manage_connectors.py pause datagen-users-source

    # Resume a paused connector
    KAFKA_ENV=onprem python3 scripts/connectors/manage_connectors.py resume datagen-users-source

    # Restart a connector (and optionally its tasks)
    KAFKA_ENV=onprem python3 scripts/connectors/manage_connectors.py restart datagen-users-source
    KAFKA_ENV=onprem python3 scripts/connectors/manage_connectors.py restart datagen-users-source --tasks

    # Delete a connector (prompts for confirmation)
    KAFKA_ENV=onprem python3 scripts/connectors/manage_connectors.py delete datagen-users-source
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from auth import get_env, http_session

_STATE_COLOUR = {
    "RUNNING":    "\033[32m",   # green
    "PAUSED":     "\033[33m",   # yellow
    "FAILED":     "\033[31m",   # red
    "UNASSIGNED": "\033[33m",
    "STOPPED":    "\033[31m",
}
_RESET = "\033[0m"


def _coloured_state(state: str) -> str:
    c = _STATE_COLOUR.get(state.upper(), "")
    return f"{c}{state}{_RESET}" if c else state


# ── list ───────────────────────────────────────────────────────────────────────

def cmd_list(session, connect_url: str) -> None:
    try:
        resp = session.get(f"{connect_url}/connectors?expand=status&expand=info",
                           timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        sys.exit(f"Failed to list connectors: {exc}")

    if not data:
        print("  No connectors deployed.")
        return

    print(f"\n  {'CONNECTOR':<45}  {'TYPE':<10}  {'STATE':<12}  {'TASKS'}")
    print(f"  {'-'*45}  {'-'*10}  {'-'*12}  {'-'*20}")

    for name, info in sorted(data.items()):
        conn_type  = info.get("info", {}).get("type", "unknown")
        status_obj = info.get("status", {}).get("connector", {})
        state      = status_obj.get("state", "?")
        tasks      = info.get("status", {}).get("tasks", [])
        task_states = "/".join(t.get("state", "?") for t in tasks) or "(none)"
        print(f"  {name:<45}  {conn_type:<10}  "
              f"{_coloured_state(state):<12}  {task_states}")

    print(f"\n  Total: {len(data)} connector(s)")


# ── describe ───────────────────────────────────────────────────────────────────

def cmd_describe(session, connect_url: str, name: str) -> None:
    try:
        status_resp = session.get(f"{connect_url}/connectors/{name}/status", timeout=15)
        config_resp = session.get(f"{connect_url}/connectors/{name}/config", timeout=15)
        status_resp.raise_for_status()
        config_resp.raise_for_status()
    except Exception as exc:
        sys.exit(f"Failed to describe connector '{name}': {exc}")

    status = status_resp.json()
    config = config_resp.json()

    conn   = status.get("connector", {})
    tasks  = status.get("tasks", [])

    print(f"\n  Connector : {name}")
    print(f"  Type      : {status.get('type', 'unknown')}")
    print(f"  State     : {_coloured_state(conn.get('state', '?'))}")
    print(f"  Worker ID : {conn.get('worker_id', 'n/a')}")

    print(f"\n  Tasks ({len(tasks)}):")
    for t in tasks:
        state = t.get("state", "?")
        trace = t.get("trace", "")
        line  = f"    Task {t['id']:>3}: {_coloured_state(state)}"
        if trace:
            line += f"  ↳ {trace[:120]}"
        print(line)

    print(f"\n  Config:")
    for k, v in sorted(config.items()):
        # Redact passwords
        display_v = "****" if "password" in k.lower() or "secret" in k.lower() else v
        print(f"    {k:<50} {display_v}")


# ── plugins ────────────────────────────────────────────────────────────────────

def cmd_plugins(session, connect_url: str) -> None:
    try:
        resp = session.get(f"{connect_url}/connector-plugins", timeout=15)
        resp.raise_for_status()
        plugins = resp.json()
    except Exception as exc:
        sys.exit(f"Failed to list plugins: {exc}")

    print(f"\n  {'PLUGIN CLASS':<80}  {'TYPE':<10}  VERSION")
    print(f"  {'-'*80}  {'-'*10}  {'-'*15}")
    for p in sorted(plugins, key=lambda x: x.get("class", "")):
        cls     = p.get("class", "?")
        ptype   = p.get("type", "?")
        version = p.get("version", "?")
        print(f"  {cls:<80}  {ptype:<10}  {version}")
    print(f"\n  Total: {len(plugins)} plugin(s)")


# ── pause ──────────────────────────────────────────────────────────────────────

def cmd_pause(session, connect_url: str, name: str) -> None:
    try:
        resp = session.put(f"{connect_url}/connectors/{name}/pause", timeout=15)
        resp.raise_for_status()
        print(f"  ✓ Connector '{name}' paused.")
    except Exception as exc:
        sys.exit(f"Failed to pause '{name}': {exc}")


# ── resume ─────────────────────────────────────────────────────────────────────

def cmd_resume(session, connect_url: str, name: str) -> None:
    try:
        resp = session.put(f"{connect_url}/connectors/{name}/resume", timeout=15)
        resp.raise_for_status()
        print(f"  ✓ Connector '{name}' resumed.")
    except Exception as exc:
        sys.exit(f"Failed to resume '{name}': {exc}")


# ── restart ────────────────────────────────────────────────────────────────────

def cmd_restart(session, connect_url: str, name: str, tasks: bool) -> None:
    try:
        resp = session.post(f"{connect_url}/connectors/{name}/restart", timeout=15)
        resp.raise_for_status()
        print(f"  ✓ Connector '{name}' restarted.")
    except Exception as exc:
        sys.exit(f"Failed to restart '{name}': {exc}")

    if tasks:
        # Restart each failed task individually
        try:
            status_resp = session.get(f"{connect_url}/connectors/{name}/status",
                                      timeout=15)
            status_resp.raise_for_status()
            for task in status_resp.json().get("tasks", []):
                tid = task["id"]
                t_resp = session.post(
                    f"{connect_url}/connectors/{name}/tasks/{tid}/restart",
                    timeout=15,
                )
                state = task.get("state", "?")
                if t_resp.status_code in (200, 204):
                    print(f"  ✓ Task {tid} restarted (was {state}).")
                else:
                    print(f"  ✗ Task {tid} restart failed: HTTP {t_resp.status_code}")
        except Exception as exc:
            print(f"  Warning: could not restart tasks: {exc}")


# ── delete ─────────────────────────────────────────────────────────────────────

def cmd_delete(session, connect_url: str, name: str) -> None:
    confirm = input(f"  Delete connector '{name}'? [y/N] ").strip().lower()
    if confirm != "y":
        print("  Aborted.")
        return
    try:
        resp = session.delete(f"{connect_url}/connectors/{name}", timeout=15)
        resp.raise_for_status()
        print(f"  ✓ Connector '{name}' deleted.")
    except Exception as exc:
        sys.exit(f"Failed to delete '{name}': {exc}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage Kafka Connect connectors.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list",    help="List all deployed connectors with state")
    sub.add_parser("plugins", help="List installed connector plugins")

    for cmd in ("describe", "pause", "resume", "delete"):
        p = sub.add_parser(cmd, help=f"{cmd.capitalize()} a connector")
        p.add_argument("name", help="Connector name")

    p_restart = sub.add_parser("restart", help="Restart a connector")
    p_restart.add_argument("name", help="Connector name")
    p_restart.add_argument("--tasks", action="store_true",
                           help="Also restart all tasks individually")

    return parser.parse_args()


if __name__ == "__main__":
    if get_env() != "onprem":
        sys.exit("manage_connectors.py only works with KAFKA_ENV=onprem")

    args = parse_args()
    session, _ = http_session("KAFKA_CONNECT_URL")
    connect_url = os.getenv("KAFKA_CONNECT_URL", "").rstrip("/")

    env = get_env()
    print(f"\n── Kafka Connect  [KAFKA_ENV={env}] ──")

    if args.command == "list":
        cmd_list(session, connect_url)
    elif args.command == "describe":
        cmd_describe(session, connect_url, args.name)
    elif args.command == "plugins":
        cmd_plugins(session, connect_url)
    elif args.command == "pause":
        cmd_pause(session, connect_url, args.name)
    elif args.command == "resume":
        cmd_resume(session, connect_url, args.name)
    elif args.command == "restart":
        cmd_restart(session, connect_url, args.name, args.tasks)
    elif args.command == "delete":
        cmd_delete(session, connect_url, args.name)
