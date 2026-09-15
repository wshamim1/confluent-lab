"""Produce messages to any Kafka topic.

Works with both KAFKA_ENV=cloud and KAFKA_ENV=onprem.

Usage
-----
    # Send a single message (value only)
    KAFKA_ENV=onprem python3 scripts/producers/produce.py --topic users \
        --value '{"name":"alice","age":30}'

    # Send with an explicit key
    KAFKA_ENV=onprem python3 scripts/producers/produce.py --topic users \
        --key alice --value '{"name":"alice","age":30}'

    # Send multiple messages from a JSON Lines file (one JSON object per line)
    KAFKA_ENV=onprem python3 scripts/producers/produce.py --topic orders \
        --file orders.jsonl

    # Read newline-delimited messages from stdin (pipe-friendly)
    echo '{"id":1}' | KAFKA_ENV=onprem python3 scripts/producers/produce.py --topic orders

    # Send a plain-text value (no JSON parsing)
    KAFKA_ENV=onprem python3 scripts/producers/produce.py --topic logs \
        --value "server started" --raw

    # Send N copies of the same message (load / smoke test)
    KAFKA_ENV=onprem python3 scripts/producers/produce.py --topic test \
        --value '{"ping":true}' --repeat 100

    # Use a specific partition
    KAFKA_ENV=onprem python3 scripts/producers/produce.py --topic users \
        --value '{"name":"bob"}' --partition 0
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from confluent_kafka import KafkaException, Producer

from auth import get_env, kafka_config


# ── delivery callback ──────────────────────────────────────────────────────────

_delivered = 0
_failed    = 0


def _delivery_report(err, msg) -> None:
    global _delivered, _failed
    if err is not None:
        _failed += 1
        print(f"  ✗ Delivery failed  partition={msg.partition()}  "
              f"error={err}", file=sys.stderr)
    else:
        _delivered += 1
        print(f"  ✓ topic={msg.topic()}  partition={msg.partition()}  "
              f"offset={msg.offset()}  key={msg.key().decode() if msg.key() else '(null)'}")


# ── core produce ───────────────────────────────────────────────────────────────

def _produce_one(producer: Producer, topic: str, key: str | None,
                 value: str, raw: bool, partition: int | None) -> None:
    """Encode and produce a single message."""
    if not raw:
        # Validate JSON before sending
        try:
            json.loads(value)
        except json.JSONDecodeError as exc:
            sys.exit(f"Value is not valid JSON: {exc}\n"
                     f"  Use --raw to send plain-text values.")

    key_bytes   = key.encode("utf-8")   if key   else None
    value_bytes = value.encode("utf-8") if value else None

    kwargs: dict = dict(
        topic    = topic,
        key      = key_bytes,
        value    = value_bytes,
        callback = _delivery_report,
    )
    if partition is not None:
        kwargs["partition"] = partition

    producer.produce(**kwargs)
    # poll to trigger delivery callbacks without blocking
    producer.poll(0)


def produce(topic: str, key: str | None, value: str | None,
            filepath: str | None, raw: bool,
            repeat: int, partition: int | None) -> None:

    env = get_env()
    cfg = kafka_config(client_id="produce-client")
    cfg.pop("session.timeout.ms", None)   # consumer-only; silences CONFWARN
    cfg.pop("group.id", None)
    producer = Producer(cfg)

    print(f"[{env}] Producing to topic '{topic}'\n")

    try:
        if filepath:
            # ── JSON Lines file ────────────────────────────────────────────────
            with open(filepath) as fh:
                lines = [l.strip() for l in fh if l.strip()]
            print(f"  Sending {len(lines)} message(s) from '{filepath}'...")
            for line in lines:
                _produce_one(producer, topic, key, line, raw, partition)

        elif not sys.stdin.isatty() and value is None:
            # ── stdin pipe ─────────────────────────────────────────────────────
            lines = [l.rstrip("\n") for l in sys.stdin if l.strip()]
            print(f"  Sending {len(lines)} message(s) from stdin...")
            for line in lines:
                _produce_one(producer, topic, key, line, raw, partition)

        else:
            # ── single value (possibly repeated) ──────────────────────────────
            if value is None:
                sys.exit("Provide --value, --file, or pipe data via stdin.")
            if repeat > 1:
                print(f"  Sending {repeat} message(s)...")
            for _ in range(repeat):
                _produce_one(producer, topic, key, value, raw, partition)

        producer.flush(timeout=30)

    except KafkaException as exc:
        sys.exit(f"Kafka error: {exc}")
    except FileNotFoundError:
        sys.exit(f"File not found: {filepath}")

    print(f"\n  Delivered: {_delivered}  Failed: {_failed}")
    if _failed:
        sys.exit(1)


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Produce messages to any Kafka topic.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--topic",     required=True, help="Target topic name")
    parser.add_argument("--key",       default=None,
                        help="Message key (optional; applied to all messages)")
    parser.add_argument("--value",     default=None,
                        help="Message value as a string (JSON by default)")
    parser.add_argument("--file",      default=None, metavar="PATH",
                        help="JSON Lines file — one message value per line")
    parser.add_argument("--raw",       action="store_true",
                        help="Treat value as plain text — skip JSON validation")
    parser.add_argument("--repeat",    type=int, default=1,
                        help="Send the same message N times (default: 1)")
    parser.add_argument("--partition", type=int, default=None,
                        help="Target partition (default: let the partitioner decide)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    produce(
        topic     = args.topic,
        key       = args.key,
        value     = args.value,
        filepath  = args.file,
        raw       = args.raw,
        repeat    = args.repeat,
        partition = args.partition,
    )
