# Tutorial: Getting Started with Confluent Kafka

## Goal

Choose a local installation path, bring up a Confluent environment, and validate the platform with basic topic operations.

## Prerequisites

- Docker or Podman installed locally
- terminal access on your machine

## Step 1: Start the Local Stack

Choose one local runtime:

```bash
docker compose up -d
```

Or:

```bash
podman compose up -d
```

Check that services are up:

```bash
docker compose ps
```

## Step 2: Verify the Kafka Broker

The local broker should be exposed at `localhost:9092`.

If you want to inspect logs:

```bash
docker compose logs broker
```

## Step 3: Prepare Python Dependencies

If you are validating with your own local client tools, install a Kafka client or use the broker container utilities. For a documentation-first setup, a console producer and consumer are enough to prove the environment is working.

```bash
kafka-topics --bootstrap-server localhost:9092 --list
```

## Step 4: Start the Consumer

In one shell:

```bash
kafka-console-consumer --bootstrap-server localhost:9092 --topic orders.created --from-beginning
```

This console consumer subscribes to the `orders.created` topic and prints each record.

## Step 5: Start the Producer

In a second shell:

```bash
kafka-console-producer --bootstrap-server localhost:9092 --topic orders.created --property parse.key=true --property key.separator=:
```

Then send records such as:

```text
1001:{"order_id":"1001","customer_id":"c-001","total_amount":49.99}
1002:{"order_id":"1002","customer_id":"c-002","total_amount":19.50}
```

## What You Should Observe

- the producer accepts keyed records
- the consumer prints received records in near real time
- records with the same key remain ordered within the partition they are assigned to

## Step 6: Explore the UI

Open Control Center at `http://localhost:9021` and inspect:

- topics
- consumer groups
- message throughput
- broker health

## Step 7: Inspect the Topic from the Broker Container

```bash
docker compose exec broker kafka-topics --bootstrap-server broker:29092 --list
docker compose exec broker kafka-console-consumer --bootstrap-server broker:29092 --topic orders.created --from-beginning
```

## Why This Matters

This basic loop demonstrates the core Kafka contract:

- producers write events to topics
- brokers durably store ordered partitions
- consumers read independently at their own pace

## Cleanup

```bash
docker compose down -v
```

Or:

```bash
podman compose down -v
```

## Next Tutorial

Proceed to `schema-registry.md` when you want a governed schema workflow instead of sending plain JSON strings.