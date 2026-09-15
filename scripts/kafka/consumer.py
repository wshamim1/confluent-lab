"""Consume messages from a Kafka topic and print them to stdout.

Works with both KAFKA_ENV=cloud and KAFKA_ENV=onprem.

Usage
-----
    # Read last 10 messages then exit
    KAFKA_ENV=onprem python3 scripts/kafka/consumer.py --topic users --limit 10

    # Read from the beginning of the topic
    KAFKA_ENV=onprem python3 scripts/kafka/consumer.py --topic users --from-beginning --limit 20

    # Stream live (no limit — Ctrl-C to stop)
    KAFKA_ENV=onprem python3 scripts/kafka/consumer.py --topic users

    # Pretty-print JSON values
    KAFKA_ENV=onprem python3 scripts/kafka/consumer.py --topic users --format json

    # Show raw bytes (hex) — useful for Avro/binary payloads
    KAFKA_ENV=onprem python3 scripts/kafka/consumer.py --topic users --format raw

    # Use a named consumer group (default: a random one-shot group)
    KAFKA_ENV=onprem python3 scripts/kafka/consumer.py --topic users --group my-group
"""

import argparse
import json
import os
import signal
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from confluent_kafka import Consumer, KafkaException, KafkaError

from auth import get_env, kafka_config

_RUNNING = True


def _handle_sigint(sig, frame):          # noqa: ARG001
    global _RUNNING
    _RUNNING = False


def _format_value(raw: bytes | None, fmt: str) -> str:
    if raw is None:
        return "(null)"
    if fmt == "raw":
        return raw.hex()
    text = raw.decode("utf-8", errors="replace")
    if fmt == "json":
        try:
            return json.dumps(json.loads(text), indent=2)
        except json.JSONDecodeError:
            return text          # fall back to plain text if not valid JSON
    return text                  # fmt == "text"


def consume(topic: str, group_id: str, from_beginning: bool,
            limit: int | None, fmt: str) -> None:
    cfg = kafka_config(client_id="consumer-client", group_id=group_id)

    # When a limit is requested without --from-beginning, default to earliest
    # so the user actually sees existing messages rather than waiting forever.
    # Explicit --from-beginning always wins; live-tail mode (no limit) defaults to latest.
    if from_beginning:
        offset_reset = "earliest"
    elif limit is not None:
        offset_reset = "earliest"
    else:
        offset_reset = "latest"

    cfg["auto.offset.reset"] = offset_reset
    # Don't commit — this is a read-only inspection tool
    cfg["enable.auto.commit"] = False

    consumer = Consumer(cfg)
    signal.signal(signal.SIGINT, _handle_sigint)

    try:
        consumer.subscribe([topic])
        count = 0
        env = get_env()
        print(f"[{env}] Consuming from '{topic}'  "
              f"(group={group_id}, offset={offset_reset}, "
              f"limit={limit or '∞'})\n"
              f"Press Ctrl-C to stop.\n")

        while _RUNNING:
            msg = consumer.poll(timeout=2.0)
            if msg is None:
                if limit is not None and count == 0:
                    # Nothing arrived yet — keep waiting
                    continue
                if not _RUNNING:
                    break
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    # Reached end of partition — only stop if we hit the limit
                    if limit is not None and count >= limit:
                        break
                    continue
                raise KafkaException(msg.error())

            count += 1
            key = msg.key().decode("utf-8", errors="replace") if msg.key() else "(null)"
            value = _format_value(msg.value(), fmt)
            ts_type, ts_ms = msg.timestamp()
            ts_label = f"{ts_ms}" if ts_type else "n/a"

            print(f"── Message {count} ──────────────────────────────────")
            print(f"  Topic     : {msg.topic()}")
            print(f"  Partition : {msg.partition()}   Offset : {msg.offset()}")
            print(f"  Timestamp : {ts_label} ms")
            print(f"  Key       : {key}")
            print(f"  Value     :")
            # indent multi-line values
            for line in value.splitlines():
                print(f"    {line}")
            print()

            if limit is not None and count >= limit:
                break

        print(f"\nTotal messages read: {count}")

    except KafkaException as exc:
        print(f"Kafka error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        consumer.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consume messages from a Kafka topic.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--topic", required=True, help="Topic name to consume from")
    parser.add_argument("--group", default=None,
                        help="Consumer group ID (default: random one-shot group)")
    parser.add_argument("--from-beginning", action="store_true",
                        help="Start from offset 0 (default: latest)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N messages (default: stream until Ctrl-C)")
    parser.add_argument("--format", choices=["text", "json", "raw"], default="text",
                        dest="fmt", help="Output format (default: text)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    group = args.group or f"consumer-inspect-{uuid.uuid4().hex[:8]}"
    consume(
        topic=args.topic,
        group_id=group,
        from_beginning=args.from_beginning,
        limit=args.limit,
        fmt=args.fmt,
    )
