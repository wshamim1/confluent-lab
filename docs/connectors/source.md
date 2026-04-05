# Source Connectors

## Purpose

Source connectors read from external systems and publish records into Kafka topics.

## Common Source Categories

### Relational Databases

- JDBC Source for table polling
- Debezium for change data capture from MySQL, PostgreSQL, SQL Server, and similar systems

Use this when:

- you need to ingest operational data into Kafka
- database change events should become replayable streams

Design notes:

- polling connectors are simpler but less real-time than CDC
- CDC gives richer change semantics but requires source database support and operational care

### SaaS Applications

- CRM, finance, ticketing, or marketing platforms through managed or third-party connectors

Use this when:

- event data originates in business SaaS systems
- the organization wants a standard ingestion path into Kafka

Design notes:

- normalize schemas early
- watch rate limits and pagination behavior

### Messaging and IoT Sources

- MQTT source
- JMS-related plugins
- HTTP-based source connectors through supported plugins

Use this when:

- device or message-oriented systems need to feed Kafka
- legacy messaging estates are being bridged into an event platform

### Object Storage Imports

- S3 source
- GCS or Azure-based object storage import patterns where supported

Use this when:

- historical data needs to be replayed into Kafka
- batch-originated files must become streaming inputs

## Typical Source Patterns

### Database to Kafka via CDC

- publish row-level changes into Kafka
- downstream services consume changes without polling the database
- use schema governance to keep contracts stable

### SaaS to Kafka

- ingest external business events into central topics
- normalize entity names and event types before many consumers depend on them

### File to Kafka

- convert landed files into Kafka topics for downstream replay or enrichment

## Example Configuration Shape

JDBC-style source connector skeleton:

```json
{
  "name": "jdbc-source-orders",
  "config": {
    "connector.class": "io.confluent.connect.jdbc.JdbcSourceConnector",
    "tasks.max": "1",
    "connection.url": "jdbc:mysql://db-host:3306/appdb",
    "connection.user": "appuser",
    "connection.password": "change-me",
    "mode": "incrementing",
    "incrementing.column.name": "id",
    "table.whitelist": "orders",
    "topic.prefix": "mysql.",
    "poll.interval.ms": "5000"
  }
}
```

## Design Caveats

- source connectors move data but do not define good domain events automatically
- poll-based ingestion can miss real-time expectations if teams assume CDC-like behavior
- connector throughput can be constrained by source API or database limits