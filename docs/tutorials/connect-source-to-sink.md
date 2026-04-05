# Tutorial: Source to Sink with Kafka Connect

## Goal

Understand the typical flow of moving data from a source system into Kafka and then from Kafka into a downstream destination.

## Scenario

You want to ingest rows from a transactional database and write them to object storage for analytics.

Flow:

1. JDBC source connector reads from a database table.
2. Connector writes records into a Kafka topic.
3. Optional consumers or stream processors validate or enrich records.
4. S3 sink connector writes topic data to object storage.

## Step 1: Start the Local Stack

Use a local Docker or Podman-based Connect environment, or an existing Connect cluster.

## Step 2: Review Source and Destination Connector Types

- see `../connectors/source.md` for source connector patterns
- see `../connectors/destinations.md` for destination connector patterns

Connector definitions are templates, not turnkey configs. You still need reachable endpoints, credentials, and installed plugins.

## Step 3: Create the Source Connector

```bash
curl -X POST http://localhost:8083/connectors \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "mysql-source-demo",
    "config": {
      "connector.class": "io.confluent.connect.jdbc.JdbcSourceConnector",
      "tasks.max": "1",
      "connection.url": "jdbc:mysql://mysql:3306/appdb",
      "connection.user": "appuser",
      "connection.password": "apppassword",
      "mode": "incrementing",
      "incrementing.column.name": "id",
      "table.whitelist": "orders",
      "topic.prefix": "mysql.",
      "poll.interval.ms": "5000"
    }
  }'
```

## Step 4: Confirm Source Status

```bash
curl http://localhost:8083/connectors/mysql-source-demo/status
```

## Step 5: Create the Sink Connector

```bash
curl -X POST http://localhost:8083/connectors \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "s3-sink-demo",
    "config": {
      "connector.class": "io.confluent.connect.s3.S3SinkConnector",
      "tasks.max": "1",
      "topics": "orders.created",
      "s3.bucket.name": "demo-bucket",
      "s3.region": "us-east-1",
      "flush.size": "3",
      "storage.class": "io.confluent.connect.s3.storage.S3Storage",
      "format.class": "io.confluent.connect.s3.format.json.JsonFormat",
      "partitioner.class": "io.confluent.connect.storage.partitioner.DefaultPartitioner"
    }
  }'
```

## Step 6: Inspect Data Movement

Check source topic activity and sink task status.

Useful calls:

```bash
curl http://localhost:8083/connectors
curl http://localhost:8083/connectors/s3-sink-demo/status
```

## Important Design Choices

### Topic Naming

- use stable names that reflect data domain, not connector implementation

### Serialization

- prefer schema-aware formats for long-lived pipelines

### Error Handling

- configure error topics or dead-letter queues where supported
- decide whether malformed records should fail fast or be redirected

### Throughput and Parallelism

- scale tasks based on source read behavior and sink write capacity
- more tasks are not always better if the destination is rate-limited

## Common Failure Modes

- plugin not installed on Connect worker
- invalid credentials or unreachable external endpoints
- converter mismatch between connector and topic data
- destination rejects records due to schema or API constraints

## When to Use Connect vs Custom Code

Use Connect when:

- you need standard integration patterns
- the connector ecosystem already covers your systems
- operational consistency matters more than custom transformation logic

Use custom apps or stream processors when:

- business transformations are complex
- orchestration or routing logic exceeds connector capabilities
- you need tight control over error semantics