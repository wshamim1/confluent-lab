# Tutorial: ksqlDB Workflow

## Goal

Use ksqlDB to create a stream over Kafka events and derive a running aggregation without writing a custom application.

## What You Need

- a local Docker or Podman runtime
- Kafka, Schema Registry, and ksqlDB running locally
- sample JSON messages on the `orders.created` topic

## Local Scripts

Generic helpers:

- `ksql/ksql-up.sh`
- `ksql/ksql-cli.sh`
- `ksql/ksql-run-demo.sh`
- `ksql/ksql-demo.sql`

These scripts auto-detect Podman first, then Docker. To force a specific runtime, set `CONTAINER_RUNTIME=docker` or `CONTAINER_RUNTIME=podman`.

## Step 1: Start the Local ksqlDB Stack

```bash
./ksql/ksql-up.sh
```

This starts Kafka, Schema Registry, Connect, ksqlDB Server, ksqlDB CLI, and Control Center.

## Step 2: Put Sample Events on the Topic

In another shell, use a console producer:

```bash
kafka-console-producer --bootstrap-server localhost:9092 --topic orders.created --property parse.key=true --property key.separator=:
```

Send a few records:

```text
1001:{"order_id":"1001","customer_id":"c-001","total_amount":49.99,"currency":"USD"}
1002:{"order_id":"1002","customer_id":"c-002","total_amount":19.50,"currency":"USD"}
1003:{"order_id":"1003","customer_id":"c-001","total_amount":120.00,"currency":"USD"}
```

## Step 3: Run the Demo SQL

```bash
./ksql/ksql-run-demo.sh
```

The demo script:

- creates a stream over `orders.created`
- creates an aggregated table of spend and order counts by customer
- shows the derived streams and tables

## Step 4: Open the Interactive CLI

```bash
./ksql/ksql-cli.sh
```

Once inside the CLI, useful commands include:

```sql
SHOW TOPICS;
SHOW STREAMS;
SHOW TABLES;
DESCRIBE orders_raw;
SELECT * FROM order_totals EMIT CHANGES;
```

## Why ksqlDB Is Useful

- it gives SQL-based stream processing over Kafka topics
- it is useful for prototyping derived views and aggregations quickly
- it reduces the amount of custom application code needed for common streaming transforms

## Caveats

- ksqlDB is strongest for streaming SQL patterns, not arbitrary business logic
- production designs still need intentional topic naming, retention, and schema governance
- long-running pull and push queries should be monitored like any other stateful streaming workload

## Next Step

Combine ksqlDB with governed schemas and connectors when you want ingestion, transformation, and delivery to stay inside the event platform.