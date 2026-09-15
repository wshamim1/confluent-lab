"""
manage_topics.py — Create, delete, describe, and list Kafka topics.

Works with both KAFKA_ENV=cloud and KAFKA_ENV=onprem.

Usage
-----
# List all user topics
python3 manage_topics.py list

# Describe one or more topics
python3 manage_topics.py describe bookings
python3 manage_topics.py describe bookings users orders

# Create a topic (defaults: 1 partition, replication factor 1 for cloud / 3 for onprem)
python3 manage_topics.py create bookings
python3 manage_topics.py create bookings --partitions 3
python3 manage_topics.py create bookings --partitions 3 --replication-factor 3
python3 manage_topics.py create bookings --config retention.ms=86400000
python3 manage_topics.py create bookings --config retention.ms=86400000 --config cleanup.policy=compact

# Delete a topic
python3 manage_topics.py delete bookings

# Delete multiple topics at once
python3 manage_topics.py delete bookings orders users
"""

import argparse
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from confluent_kafka.admin import AdminClient, NewTopic, ConfigResource, ResourceType
from confluent_kafka import KafkaException

from auth import get_env, kafka_config


# ── Admin client ──────────────────────────────────────────────────────────────

def make_admin() -> AdminClient:
    cfg = kafka_config(client_id="manage-topics")
    # Remove consumer-only properties that AdminClient warns about
    cfg.pop("session.timeout.ms", None)
    cfg.pop("group.id", None)
    return AdminClient(cfg)


# ── List ──────────────────────────────────────────────────────────────────────

def cmd_list(admin: AdminClient):
    meta = admin.list_topics(timeout=20)
    topics = sorted(
        name for name in meta.topics
        if not name.startswith("_") and not name.startswith("confluent.")
    )
    if not topics:
        print("  (no user topics found)")
        return
    print(f"  {'TOPIC':<40}  {'PARTITIONS':>10}  {'REPLICAS':>8}")
    print(f"  {'-'*40}  {'-'*10}  {'-'*8}")
    for name in topics:
        t = meta.topics[name]
        parts    = len(t.partitions)
        replicas = len(next(iter(t.partitions.values())).replicas) if t.partitions else 0
        print(f"  {name:<40}  {parts:>10}  {replicas:>8}")
    print(f"\n  Total: {len(topics)} topic(s)")


# ── Describe ──────────────────────────────────────────────────────────────────

def cmd_describe(admin: AdminClient, names: list[str]):
    meta = admin.list_topics(timeout=20)

    for name in names:
        if name not in meta.topics:
            print(f"  ✗ Topic '{name}' not found.\n")
            continue

        t = meta.topics[name]
        print(f"\n  Topic : {name}")
        print(f"  Partitions : {len(t.partitions)}")
        for pid, p in sorted(t.partitions.items()):
            leader   = p.leader
            replicas = p.replicas
            isrs     = p.isrs
            print(f"    Partition {pid}: leader={leader}  replicas={replicas}  isr={isrs}")

        # Fetch topic config via AdminClient
        resource = ConfigResource(ResourceType.TOPIC, name)
        fs = admin.describe_configs([resource])
        for res, f in fs.items():
            try:
                cfg = f.result()
                non_default = {
                    k: v.value for k, v in cfg.items()
                    if not v.is_default
                }
                if non_default:
                    print(f"  Config overrides:")
                    for k, v in sorted(non_default.items()):
                        print(f"    {k} = {v}")
            except Exception as e:
                print(f"  Config fetch error: {e}")


# ── Create ────────────────────────────────────────────────────────────────────

def cmd_create(admin: AdminClient, name: str, partitions: int,
               replication_factor: int, configs: dict[str, str]):
    new_topic = NewTopic(
        name,
        num_partitions=partitions,
        replication_factor=replication_factor,
        config=configs,
    )
    futures = admin.create_topics([new_topic], validate_only=False)

    for topic, f in futures.items():
        try:
            f.result()
            cfg_str = ""
            if configs:
                cfg_str = "  config: " + ", ".join(f"{k}={v}" for k, v in configs.items())
            print(f"  ✓ Created '{topic}'  "
                  f"(partitions={partitions}, replication={replication_factor}){cfg_str}")
        except KafkaException as e:
            err = e.args[0]
            if err.code() == err.TOPIC_ALREADY_EXISTS:
                print(f"  Topic '{topic}' already exists — skipping.")
            else:
                print(f"  ✗ Failed to create '{topic}': {e}", file=sys.stderr)
                sys.exit(1)


# ── Delete ────────────────────────────────────────────────────────────────────

def cmd_delete(admin: AdminClient, names: list[str]):
    futures = admin.delete_topics(names, operation_timeout=30)
    for topic, f in futures.items():
        try:
            f.result()
            print(f"  ✓ Deleted '{topic}'")
        except KafkaException as e:
            err = e.args[0]
            if err.code() == err.UNKNOWN_TOPIC_OR_PART:
                print(f"  Topic '{topic}' not found — nothing to delete.")
            else:
                print(f"  ✗ Failed to delete '{topic}': {e}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Create, delete, describe, and list Kafka topics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    sub.add_parser("list", help="List all user topics")

    # describe
    p_desc = sub.add_parser("describe", help="Describe one or more topics")
    p_desc.add_argument("topics", nargs="+", help="Topic name(s)")

    # create
    p_create = sub.add_parser("create", help="Create a topic")
    p_create.add_argument("topic", help="Topic name")
    p_create.add_argument("--partitions",         type=int, default=None,
                          help="Number of partitions (default: 1 cloud / 3 onprem)")
    p_create.add_argument("--replication-factor", type=int, default=None,
                          help="Replication factor (default: 1 cloud / 3 onprem)")
    p_create.add_argument("--config", action="append", metavar="KEY=VALUE",
                          help="Topic config override; repeat for multiple (e.g. retention.ms=86400000)")

    # delete
    p_del = sub.add_parser("delete", help="Delete one or more topics")
    p_del.add_argument("topics", nargs="+", help="Topic name(s) to delete")

    return parser.parse_args()


def main():
    args  = parse_args()
    env   = get_env()
    print(f"\n── Kafka Topics  [KAFKA_ENV={env}] ──")

    admin = make_admin()

    if args.command == "list":
        cmd_list(admin)

    elif args.command == "describe":
        cmd_describe(admin, args.topics)

    elif args.command == "create":
        # Sensible defaults per environment
        default_parts  = 3 if env == "onprem" else 1
        default_rf     = 3 if env == "onprem" else 1
        partitions     = args.partitions         or default_parts
        replication    = args.replication_factor or default_rf

        # Parse --config KEY=VALUE pairs
        configs = {}
        for item in (args.config or []):
            if "=" not in item:
                sys.exit(f"--config must be KEY=VALUE, got: '{item}'")
            k, v = item.split("=", 1)
            configs[k.strip()] = v.strip()

        cmd_create(admin, args.topic, partitions, replication, configs)

    elif args.command == "delete":
        # Confirm before deleting
        print(f"  About to delete: {', '.join(args.topics)}")
        confirm = input("  Confirm? [y/N] ").strip().lower()
        if confirm != "y":
            print("  Aborted.")
            sys.exit(0)
        cmd_delete(admin, args.topics)

    admin.poll(0)


if __name__ == "__main__":
    main()
