"""Print Kafka cluster metadata and topic details for the active environment.

Set KAFKA_ENV=cloud  to inspect the Confluent Cloud cluster.
Set KAFKA_ENV=onprem to inspect the on-prem VM cluster via Control Center.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from confluent_kafka import Consumer, KafkaException

from auth import get_env, http_session, kafka_config


def cloud_cluster_details():
    consumer = Consumer(kafka_config(
        client_id="cluster-details-client",
        group_id="cluster-details-client",
    ))
    try:
        metadata = consumer.list_topics(timeout=10)
        topics = sorted(metadata.topics)

        print(f"Bootstrap server : {consumer.memberid() or 'n/a'}")
        print(f"Broker count     : {len(metadata.brokers)}")
        print(f"Visible topics   : {len(topics)}")
        print(f"Cluster ID       : {metadata.cluster_id}")

        if topics:
            print("\nTopics:")
            for name in topics:
                topic = metadata.topics[name]
                print(f"  - {name} (partitions={len(topic.partitions)})")
        else:
            print("No topics visible to this API key.")
    except KafkaException as error:
        print(f"Kafka error: {error}", file=sys.stderr)
        sys.exit(1)
    finally:
        consumer.close()


def onprem_cluster_details():
    session, base_url = http_session()

    # Discover clusters
    try:
        resp = session.get(f"{base_url}/kafka/v3/clusters", timeout=10)
        resp.raise_for_status()
        clusters = resp.json().get("data", [])
        if not clusters:
            print("No Kafka clusters found via Control Center REST API.")
            return
    except Exception as error:
        sys.exit(f"Could not reach Control Center at {base_url}: {error}")

    for cluster in clusters:
        cluster_id   = cluster["cluster_id"]
        cluster_name = cluster.get("cluster_name", cluster_id)
        controller   = cluster.get("controller", {}).get("related", "n/a")

        print(f"Cluster          : {cluster_name}")
        print(f"Cluster ID       : {cluster_id}")
        print(f"Controller       : {controller}")

        # Brokers
        try:
            resp = session.get(
                f"{base_url}/kafka/v3/clusters/{cluster_id}/brokers", timeout=10
            )
            resp.raise_for_status()
            brokers = resp.json().get("data", [])
            print(f"Broker count     : {len(brokers)}")
        except Exception:
            print("Broker count     : (unavailable)")

        # Topics
        try:
            resp = session.get(
                f"{base_url}/kafka/v3/clusters/{cluster_id}/topics", timeout=10
            )
            resp.raise_for_status()
            topics = sorted(t["topic_name"] for t in resp.json().get("data", []))
            print(f"Visible topics   : {len(topics)}")
            if topics:
                print("\nTopics:")
                for name in topics:
                    print(f"  - {name}")
            else:
                print("No topics found.")
        except Exception as error:
            print(f"Error listing topics: {error}", file=sys.stderr)


if __name__ == "__main__":
    env = get_env()
    print(f"[{env}] Cluster details...\n")
    if env == "cloud":
        cloud_cluster_details()
    else:
        onprem_cluster_details()
