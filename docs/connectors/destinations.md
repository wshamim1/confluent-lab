# Destination Connectors

## Purpose

Destination connectors, often called sink connectors, read Kafka topics and write records to external systems.

## Common Destination Categories

### Object Storage and Data Lakes

- S3 sink
- GCS sink
- Azure Blob Storage sink

Use this when:

- Kafka data needs durable analytical storage
- replayable topic data should be written to a lakehouse or archive tier

Design notes:

- choose partitioning strategy carefully
- align file format with downstream analytics expectations

### Search and Serving

- Elasticsearch sink
- OpenSearch sink

Use this when:

- Kafka events must power search, dashboards, or document views
- upsert semantics matter more than append-only storage

Design notes:

- define stable keys for idempotent indexing
- account for mapping drift between events and search schemas

### Warehouses and Analytics Targets

- Snowflake
- BigQuery
- Redshift

Use this when:

- Kafka topics feed analytics or BI systems
- near-real-time loading is needed without hand-built ETL jobs

### Operational Databases and Services

- JDBC sink
- HTTP sink through supported plugins
- messaging or notification endpoints where appropriate connectors exist

Use this when:

- downstream operational systems must consume curated Kafka topics
- integration teams need repeatable export pipelines

## Typical Destination Patterns

### Kafka to Data Lake

- write topics to object storage
- partition by topic, date, or business key
- retain Kafka for streaming and the lake for analytics and archival access

### Kafka to Search Index

- project curated topics into searchable views
- use compaction or stable keys where point-in-time view consistency matters

### Kafka to Warehouse

- move analytical topics into queryable warehouse tables
- align schema evolution strategy across Kafka and warehouse models

## Example Configuration Shape

S3-style sink connector skeleton:

```json
{
  "name": "s3-sink-orders",
  "config": {
    "connector.class": "io.confluent.connect.s3.S3SinkConnector",
    "tasks.max": "1",
    "topics": "orders.created",
    "s3.bucket.name": "analytics-bucket",
    "s3.region": "us-east-1",
    "flush.size": "1000",
    "storage.class": "io.confluent.connect.s3.storage.S3Storage",
    "format.class": "io.confluent.connect.s3.format.json.JsonFormat",
    "partitioner.class": "io.confluent.connect.storage.partitioner.DefaultPartitioner"
  }
}
```

## Design Caveats

- sink throughput is often constrained by destination API limits or storage commit behavior
- connector success does not guarantee downstream semantic correctness
- warehouse, search, and lake targets all need explicit idempotency and schema planning