"""List consumer groups, show per-partition lag, and reset offsets.

Works with both KAFKA_ENV=cloud and KAFKA_ENV=onprem.

Usage
-----
    # List all consumer groups
    KAFKA_ENV=onprem python3 scripts/kafka/consumer_groups.py list

    # Show lag for a specific group across all its topics
    KAFKA_ENV=onprem python3 scripts/kafka/consumer_groups.py lag --group my-group

    # Show lag for a group on a specific topic
    KAFKA_ENV=onprem python3 scripts/kafka/consumer_groups.py lag --group my-group --topic users

    # Reset offsets to earliest (requires the group to be inactive)
    KAFKA_ENV=onprem python3 scripts/kafka/consumer_groups.py reset --group my-group --topic users --to earliest

    # Reset offsets to latest
    KAFKA_ENV=onprem python3 scripts/kafka/consumer_groups.py reset --group my-group --topic users --to latest
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from confluent_kafka import Consumer, KafkaException, TopicPartition
from confluent_kafka.admin import AdminClient

from auth import get_env, kafka_config


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_admin() -> AdminClient:
    cfg = kafka_config(client_id="consumer-groups-admin")
    cfg.pop("group.id", None)
    cfg.pop("session.timeout.ms", None)
    return AdminClient(cfg)


def _make_consumer(group_id: str) -> Consumer:
    cfg = kafka_config(client_id="consumer-groups-client", group_id=group_id)
    cfg["enable.auto.commit"] = False
    return Consumer(cfg)


# ── list ───────────────────────────────────────────────────────────────────────

def cmd_list(admin: AdminClient) -> None:
    env = get_env()
    print(f"\n── Consumer Groups  [KAFKA_ENV={env}] ──\n")

    future = admin.list_groups(timeout=15)
    try:
        groups = future
    except Exception as exc:
        sys.exit(f"Failed to list groups: {exc}")

    # filter out internal Confluent/Kafka groups
    user_groups = sorted(
        g for g in groups
        if not g.id.startswith("_") and not g.id.startswith("confluent.")
    )

    if not user_groups:
        print("  No user consumer groups found.")
        return

    print(f"  {'GROUP':<50}  {'STATE':<15}  {'MEMBERS':>7}")
    print(f"  {'-'*50}  {'-'*15}  {'-'*7}")
    for g in user_groups:
        state   = g.state.name if hasattr(g.state, "name") else str(g.state)
        members = len(g.members)
        print(f"  {g.id:<50}  {state:<15}  {members:>7}")
    print(f"\n  Total: {len(user_groups)} group(s)")


# ── lag ────────────────────────────────────────────────────────────────────────

def cmd_lag(admin: AdminClient, group_id: str, topic_filter: str | None) -> None:
    env = get_env()
    print(f"\n── Consumer Lag  [{env}]  group={group_id} ──\n")

    # 1. Find committed offsets for the group
    consumer = _make_consumer(group_id)
    try:
        meta = consumer.list_topics(timeout=15)
    except KafkaException as exc:
        consumer.close()
        sys.exit(f"Kafka error: {exc}")

    # Build list of TopicPartitions for all topics (or the filtered one)
    tps: list[TopicPartition] = []
    for topic_name, topic_meta in meta.topics.items():
        if topic_name.startswith("_") or topic_name.startswith("confluent."):
            continue
        if topic_filter and topic_name != topic_filter:
            continue
        for pid in topic_meta.partitions:
            tps.append(TopicPartition(topic_name, pid))

    if not tps:
        label = f"topic '{topic_filter}'" if topic_filter else "any topic"
        print(f"  No partitions found for {label}.")
        consumer.close()
        return

    # 2. Fetch committed offsets for this group
    committed = consumer.committed(tps, timeout=15)

    # 3. Fetch end (high-water) offsets for each partition
    watermarks: dict[tuple[str, int], tuple[int, int]] = {}
    for tp in committed:
        try:
            lo, hi = consumer.get_watermark_offsets(tp, timeout=10)
            watermarks[(tp.topic, tp.partition)] = (lo, hi)
        except Exception:
            watermarks[(tp.topic, tp.partition)] = (0, 0)

    consumer.close()

    # 4. Print lag table
    print(f"  {'TOPIC':<35}  {'PART':>4}  {'COMMITTED':>10}  {'END':>10}  {'LAG':>8}")
    print(f"  {'-'*35}  {'-'*4}  {'-'*10}  {'-'*10}  {'-'*8}")

    total_lag = 0
    for tp in sorted(committed, key=lambda t: (t.topic, t.partition)):
        committed_off = tp.offset if tp.offset >= 0 else 0
        lo, hi        = watermarks.get((tp.topic, tp.partition), (0, 0))
        lag           = max(0, hi - committed_off)
        total_lag    += lag
        committed_str = str(committed_off) if tp.offset >= 0 else "(uncommitted)"
        print(f"  {tp.topic:<35}  {tp.partition:>4}  {committed_str:>10}  {hi:>10}  {lag:>8}")

    print(f"\n  Total lag: {total_lag}")


# ── reset ──────────────────────────────────────────────────────────────────────

def cmd_reset(group_id: str, topic: str, to: str) -> None:
    env = get_env()
    print(f"\n── Reset Offsets  [{env}]  group={group_id}  topic={topic}  to={to} ──\n")

    consumer = _make_consumer(group_id)
    try:
        meta = consumer.list_topics(topic, timeout=15)
    except KafkaException as exc:
        consumer.close()
        sys.exit(f"Kafka error: {exc}")

    if topic not in meta.topics:
        consumer.close()
        sys.exit(f"Topic '{topic}' not found.")

    tps = [TopicPartition(topic, pid)
           for pid in meta.topics[topic].partitions]

    if to == "earliest":
        for tp in tps:
            tp.offset = -2      # OFFSET_BEGINNING
    elif to == "latest":
        for tp in tps:
            lo, hi = consumer.get_watermark_offsets(tp, timeout=10)
            tp.offset = hi
    else:
        try:
            off = int(to)
        except ValueError:
            consumer.close()
            sys.exit(f"--to must be 'earliest', 'latest', or an integer offset, got: '{to}'")
        for tp in tps:
            tp.offset = off

    confirm = input(
        f"  Reset {len(tps)} partition(s) of '{topic}' to '{to}'? [y/N] "
    ).strip().lower()
    if confirm != "y":
        print("  Aborted.")
        consumer.close()
        return

    consumer.commit(offsets=tps)
    for tp in tps:
        print(f"  ✓ {topic}[{tp.partition}] → offset {tp.offset}")

    consumer.close()


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List consumer groups, show lag, reset offsets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all user consumer groups")

    p_lag = sub.add_parser("lag", help="Show per-partition lag for a group")
    p_lag.add_argument("--group", required=True, help="Consumer group ID")
    p_lag.add_argument("--topic", default=None, help="Filter to a single topic (optional)")

    p_reset = sub.add_parser("reset", help="Reset committed offsets for a group+topic")
    p_reset.add_argument("--group", required=True, help="Consumer group ID")
    p_reset.add_argument("--topic", required=True, help="Topic name")
    p_reset.add_argument("--to", required=True,
                         help="earliest | latest | <integer offset>")

    return parser.parse_args()


if __name__ == "__main__":
    args  = parse_args()
    admin = _make_admin()

    if args.command == "list":
        cmd_list(admin)
    elif args.command == "lag":
        cmd_lag(admin, args.group, getattr(args, "topic", None))
    elif args.command == "reset":
        cmd_reset(args.group, args.topic, args.to)
