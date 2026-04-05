# Kafka Connect Guides

This section organizes Kafka Connect material by direction of data movement.

## What Kafka Connect Solves

Kafka Connect standardizes data movement between Kafka and external systems. Instead of writing and operating custom ingestion jobs for every source or sink, you configure connectors that run inside Connect workers.

## Runtime Concepts

- workers: processes that run connector tasks
- connector: logical integration definition
- task: unit of work for a connector
- converter: serialization layer between Kafka bytes and the Connect data model
- transforms: lightweight record transformations applied in-flight

## Deployment Modes

### Standalone

- one process
- useful for local evaluation
- not fault tolerant

### Distributed

- multiple workers share connector load
- connector configs and offsets are stored in Kafka topics
- supports failover and scaling

## Internal Connect Topics

In distributed mode, Connect stores operational state in Kafka topics such as:

- config topic
- offsets topic
- status topic

These topics should be compacted and treated as platform-critical metadata.

## Converter Choices

### JSON Converter

- easy to inspect
- less governed unless used carefully with schemas enabled

### Avro Converter

- compact and schema-driven
- commonly paired with Schema Registry

### Protobuf Converter

- strong typed contracts and good cross-language support

### JSON Schema Converter

- a practical fit for teams standardized on JSON contracts

## Operational Guidance

- pin plugin versions intentionally
- isolate noisy connectors from critical ones when scaling workers
- define dead-letter topics where supported
- monitor task failures, restarts, rebalance events, retries, and backpressure

## Connector Navigation

- `source.md` covers systems that publish data into Kafka
- `destinations.md` covers systems that consume Kafka data downstream