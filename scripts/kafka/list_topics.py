"""List Kafka topics for the active environment (cloud or onprem).

Set KAFKA_ENV=cloud  to list topics from Confluent Cloud.
Set KAFKA_ENV=onprem to list topics from the on-prem VM via Control Center.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from confluent_kafka import Consumer, KafkaException

from auth import get_env, kafka_config


def list_cloud_topics():
    consumer = Consumer(kafka_config(
        client_id="topic-listing-client",
        group_id="topic-listing-client",
    ))
    try:
        metadata = consumer.list_topics(timeout=20)
        topics = sorted(metadata.topics)
        if not topics:
            print("No topics found. Connection succeeded but no topics visible for this API key.")
        else:
            print(f"Found {len(topics)} topic(s):")
            for topic in topics:
                print(f"  - {topic}")
    except KafkaException as error:
        print(f"Kafka error: {error}", file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(f"Unexpected error: {error}", file=sys.stderr)
        sys.exit(1)
    finally:
        consumer.close()


def list_onprem_topics():
    """List topics via native Kafka protocol (SASL_SSL, ports 9094-9096)."""
    consumer = Consumer(kafka_config(
        client_id="topic-listing-client",
        group_id="topic-listing-client",
    ))
    try:
        metadata = consumer.list_topics(timeout=20)
        topics = sorted(
            name for name in metadata.topics
            if not name.startswith("_")   # skip internal topics
        )
        if not topics:
            print("No topics found (broker reachable, but no user topics exist yet).")
            print("Tip: deploy a datagen connector to create one:")
            print("  ssh -i cflt-vsi-key.pem root@163.66.88.209 "
                  "'bash /opt/confluent-installer/scripts/deploy-datagen-connector.sh users'")
        else:
            print(f"Found {len(topics)} topic(s):")
            for topic in topics:
                t = metadata.topics[topic]
                print(f"  - {topic} (partitions={len(t.partitions)})")
    except KafkaException as error:
        print(f"Kafka error: {error}", file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(f"Unexpected error: {error}", file=sys.stderr)
        sys.exit(1)
    finally:
        consumer.close()


if __name__ == "__main__":
    env = get_env()
    print(f"[{env}] Listing topics...\n")
    if env == "cloud":
        list_cloud_topics()
    else:
        list_onprem_topics()
