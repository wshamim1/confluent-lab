# Confluent Kafka Lab

This repository is a compact learning pack for Confluent Kafka. It includes:

- tutorials for core workflows
- architecture notes for Confluent Platform and Confluent Cloud
- installation guides for local, managed, container, and OpenShift environments
- connector guidance organized by source and destination patterns
- practical tutorials for local evaluation and platform planning

## Repository Tree

```text
confluent-lab/
├── docs/
│   ├── architecture.md
│   ├── connectors/
│   ├── install/
│   ├── tutorials/
│   └── use-cases/
├── examples/
│   ├── connectors/
│   ├── ksql/
│   ├── security/
│   └── schema-registry/
├── scripts/
│   └── install/
│       ├── docker/
│       ├── kubernetes/
│       └── podman/
└── README.md
```

## Who This Is For

- developers new to Apache Kafka and Confluent
- platform engineers evaluating deployment options
- data engineers working with Kafka Connect and Schema Registry
- teams that need a quick internal reference without reading the full platform docs first

## Repository Layout

- `docs/architecture.md` - Confluent Kafka architecture and component roles
- `docs/use-cases/README.md` - real-world architecture scenarios and design patterns
- `docs/install/README.md` - installation index and path selection guide
- `docs/install/options.md` - cloud, local, and self-managed installation paths
- `docs/install/podman.md` - running the local lab with Podman
- `docs/install/openshift.md` - OpenShift-oriented deployment guidance
- `docs/connectors/README.md` - Kafka Connect overview and navigation
- `docs/connectors/source.md` - source connector types and design patterns
- `docs/connectors/destinations.md` - sink connector types and destination patterns
- `docs/tutorials/getting-started.md` - first local environment and first messages
- `docs/tutorials/core-streaming.md` - brokers, topics, partitions, producers, consumers, and replay
- `docs/tutorials/delivery-semantics.md` - at-most-once, at-least-once, exactly-once, and offset commit patterns
- `docs/tutorials/topic-design-and-partitions.md` - naming, keys, partition counts, compaction, and retention strategy
- `docs/tutorials/consumer-groups-and-lag.md` - group coordination, rebalancing, lag interpretation, and scaling limits
- `docs/tutorials/kafka-security.md` - TLS, SSL, SASL, listeners, ACLs, and secure setup patterns
- `docs/tutorials/kafka-security-local-setup.md` - hands-on local secure broker and client configuration example
- `docs/tutorials/schema-registry.md` - Schema Registry and event schema workflow
- `docs/tutorials/ksqldb.md` - ksqlDB streams, tables, and aggregation workflow
- `docs/tutorials/connect-source-to-sink.md` - source and sink data movement tutorial
- `scripts/install/` - runtime-specific Docker, Podman, and Kubernetes/OpenShift setup assets
- `examples/connectors/` - source and destination connector JSON templates
- `examples/security/` - local security configuration examples and ACL templates
- `examples/schema-registry/` - Schema Registry helper scripts
- `examples/ksql/` - generic ksqlDB scripts and demo SQL

## Suggested Learning Path

1. Read `docs/install/README.md` to choose an environment.
2. Follow `docs/tutorials/getting-started.md`.
3. Follow `docs/tutorials/core-streaming.md` to understand Kafka fundamentals.
4. Follow `docs/tutorials/delivery-semantics.md` to understand delivery guarantees and offset handling.
5. Follow `docs/tutorials/topic-design-and-partitions.md` to design topics, keys, and partition counts intentionally.
6. Follow `docs/tutorials/consumer-groups-and-lag.md` to understand scaling limits, rebalancing, and lag behavior.
7. Follow `docs/tutorials/kafka-security.md` to understand TLS, SASL, ACLs, and secure client setup.
8. Follow `docs/tutorials/kafka-security-local-setup.md` for a concrete local secure configuration example.
9. Review `docs/connectors/README.md` for integration concepts.
10. Use `docs/connectors/source.md` and `docs/connectors/destinations.md` to map systems to connectors.
11. Read `docs/architecture.md` to understand platform components.
12. Follow `docs/tutorials/schema-registry.md` for governed events.
13. Follow `docs/tutorials/ksqldb.md` for streaming SQL workflows.
14. Follow `docs/tutorials/connect-source-to-sink.md` for integration patterns.
15. Review `docs/use-cases/README.md` for production-oriented reference scenarios.
16. Use the install guides to decide how to run local, cloud, or OpenShift-based environments.

## Quick Start

Choose an installation path:

```bash
ls docs/install
```

Start with the installation index:

```bash
open docs/install/README.md
```

Then review connector guidance:

```bash
open docs/connectors/README.md
```

Continue with the getting started tutorial:

```bash
open docs/tutorials/getting-started.md
```

## Notes

- The repository is documentation-first and is intended as a structured Confluent Kafka reference.
- Connector configuration snippets are documented in the connector guides instead of being stored as separate example files.
- Installation choices should be driven by operational maturity, security constraints, and platform ownership.