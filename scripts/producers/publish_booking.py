"""Publish a booking message to Kafka for the active environment.

Set KAFKA_ENV=cloud  to publish to Confluent Cloud.
Set KAFKA_ENV=onprem to publish to the on-prem VM broker.
"""

import argparse
import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from confluent_kafka import KafkaException, Producer

from auth import get_env, kafka_config


def delivery_report(error, message):
    if error is not None:
        print(f"Delivery failed: {error}", file=sys.stderr)
        return
    print(
        f"Published to {message.topic()} "
        f"(partition={message.partition()}, offset={message.offset()})"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--booking-id", default="B-TEST-001")
    parser.add_argument("--customer-email", default="wilson@test.com")
    args = parser.parse_args()

    env = get_env()
    print(f"[{env}] Publishing booking...\n")

    producer = Producer(kafka_config(
        client_id="booking-producer",
    ))

    booking = {
        "booking_id":     args.booking_id,
        "customer_email": args.customer_email,
    }

    try:
        producer.produce(
            "bookings",
            value=json.dumps(booking).encode("utf-8"),
            callback=delivery_report,
        )
        producer.flush()
    except KafkaException as error:
        sys.exit(f"Kafka error while publishing booking: {error}")


if __name__ == "__main__":
    main()
