# Tutorial: ksqlDB Workflow

## Goal

Use ksqlDB to create a stream over Kafka events and derive a running aggregation without writing a custom application.

## What You Need

- a local Docker or Podman runtime
- Kafka, Schema Registry, and ksqlDB running locally
- sample JSON messages on the `orders.created` topic

## Local Scripts

Docker helpers:

- `Install-scripts/docker/ksql-up.sh`
- `Install-scripts/docker/ksql-cli.sh`
- `Install-scripts/docker/ksql-run-demo.sh`
- `Install-scripts/docker/ksql-demo.sql`

Podman helpers:

- `Install-scripts/podman/ksql-up.sh`
- `Install-scripts/podman/ksql-cli.sh`
- `Install-scripts/podman/ksql-run-demo.sh`
- `Install-scripts/podman/ksql-demo.sql`

## Step 1: Start the Local ksqlDB Stack

With Docker:

```bash
./Install-scripts/docker/ksql-up.sh
```

With Podman:

```bash
./Install-scripts/podman/ksql-up.sh
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

With Docker:

```bash
./Install-scripts/docker/ksql-run-demo.sh
```

With Podman:

```bash
./Install-scripts/podman/ksql-run-demo.sh
```

The demo script:

- creates a stream over `orders.created`
- creates an aggregated table of spend and order counts by customer
- shows the derived streams and tables

## Step 4: Open the Interactive CLI

With Docker:

```bash
./Install-scripts/docker/ksql-cli.sh
```

With Podman:

```bash
./Install-scripts/podman/ksql-cli.sh
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