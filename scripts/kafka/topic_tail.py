"""Live tail of a Kafka topic — like `tail -f` for Kafka.

Seeks each partition to the end and streams new messages as they arrive,
printing a compact one-liner per message (or pretty JSON for structured data).

Works with both KAFKA_ENV=cloud and KAFKA_ENV=onprem.

Usage
-----
    # Tail live messages (compact one-liner per message)
    KAFKA_ENV=onprem python3 scripts/kafka/topic_tail.py --topic users

    # Pretty-print JSON values
    KAFKA_ENV=onprem python3 scripts/kafka/topic_tail.py --topic users --format json

    # Stop after N messages
    KAFKA_ENV=onprem python3 scripts/kafka/topic_tail.py --topic users --limit 5

    # Show timestamps
    KAFKA_ENV=onprem python3 scripts/kafka/topic_tail.py --topic users --timestamps

    # Tail multiple topics at once
    KAFKA_ENV=onprem python3 scripts/kafka/topic_tail.py --topic users orders
"""

import argparse
import json
import os
import signal
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from confluent_kafka import Consumer, KafkaException, KafkaError, TopicPartition

from auth import get_env, kafka_config

_RUNNING = True


def _handle_sigint(sig, frame):   # noqa: ARG001
    global _RUNNING
    _RUNNING = False


def _short_value(raw: bytes | None, fmt: str, max_len: int = 120) -> str:
    if raw is None:
        return "(null)"
    text = raw.decode("utf-8", errors="replace")
    if fmt == "json":
        try:
            parsed = json.loads(text)
            pretty = json.dumps(parsed, indent=2)
            return "\n" + "\n".join(f"    {l}" for l in pretty.splitlines())
        except json.JSONDecodeError:
            pass
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def tail(topics: list[str], fmt: str, limit: int | None, show_ts: bool) -> None:
    group_id = f"topic-tail-{uuid.uuid4().hex[:8]}"
    cfg = kafka_config(client_id="topic-tail-client", group_id=group_id)
    cfg["auto.offset.reset"]  = "latest"
    cfg["enable.auto.commit"] = False

    consumer = Consumer(cfg)
    signal.signal(signal.SIGINT, _handle_sigint)

    env = get_env()
    print(f"[{env}] Tailing topic(s): {', '.join(topics)}  "
          f"(limit={limit or '∞'})  Press Ctrl-C to stop.\n")

    try:
        # Assign each partition at its current end offset so we only see NEW messages
        all_tps: list[TopicPartition] = []
        meta = consumer.list_topics(timeout=15)
        for topic in topics:
            if topic not in meta.topics:
                print(f"  ✗ Topic '{topic}' not found — skipping.", file=sys.stderr)
                continue
            for pid in meta.topics[topic].partitions:
                tp = TopicPartition(topic, pid)
                _, hi = consumer.get_watermark_offsets(tp, timeout=10)
                tp.offset = hi          # start at the current end
                all_tps.append(tp)

        if not all_tps:
            print("No valid partitions to tail.")
            return

        consumer.assign(all_tps)

        count = 0
        while _RUNNING:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(msg.error())

            count += 1
            key   = msg.key().decode("utf-8", errors="replace") if msg.key() else "-"
            value = _short_value(msg.value(), fmt)

            if show_ts:
                _, ts_ms = msg.timestamp()
                ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
                    "%H:%M:%S.%f"
                )[:-3]
                prefix = f"[{ts}] "
            else:
                prefix = ""

            if fmt == "json" and value.startswith("\n"):
                # multi-line JSON — print header then indented value
                print(f"{prefix}{msg.topic()}[{msg.partition()}]@{msg.offset()}  "
                      f"key={key}{value}")
            else:
                print(f"{prefix}{msg.topic()}[{msg.partition()}]@{msg.offset()}  "
                      f"key={key}  value={value}")

            if limit is not None and count >= limit:
                break

    except KafkaException as exc:
        print(f"Kafka error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        consumer.close()

    print(f"\nTotal messages received: {count}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live tail of one or more Kafka topics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--topic", nargs="+", required=True,
                        help="Topic name(s) to tail")
    parser.add_argument("--format", choices=["text", "json"], default="text",
                        dest="fmt", help="Output format (default: text)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N messages (default: stream until Ctrl-C)")
    parser.add_argument("--timestamps", action="store_true",
                        help="Prefix each message with its event timestamp")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    tail(
        topics=args.topic,
        fmt=args.fmt,
        limit=args.limit,
        show_ts=args.timestamps,
    )
