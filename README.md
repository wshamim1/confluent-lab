# Confluent Kafka Lab

This repository is a compact learning pack for Confluent Kafka. It includes:

- tutorials for core workflows
- architecture notes for Confluent Platform and Confluent Cloud
- installation guides for local, managed, container, and OpenShift environments
- connector guidance organized by source and destination patterns
- practical tutorials for local evaluation and platform planning

## Who This Is For

- developers new to Apache Kafka and Confluent
- platform engineers evaluating deployment options
- data engineers working with Kafka Connect and Schema Registry
- teams that need a quick internal reference without reading the full platform docs first

## Repository Layout

- `docs/architecture.md` - Confluent Kafka architecture and component roles
- `docs/install/README.md` - installation index and path selection guide
- `docs/install/options.md` - cloud, local, and self-managed installation paths
- `docs/install/podman.md` - running the local lab with Podman
- `docs/install/openshift.md` - OpenShift-oriented deployment guidance
- `docs/connectors/README.md` - Kafka Connect overview and navigation
- `docs/connectors/source.md` - source connector types and design patterns
- `docs/connectors/destinations.md` - sink connector types and destination patterns
- `docs/tutorials/getting-started.md` - first local environment and first messages
- `docs/tutorials/schema-registry.md` - Schema Registry and event schema workflow
- `docs/tutorials/ksqldb.md` - ksqlDB streams, tables, and aggregation workflow
- `docs/tutorials/connect-source-to-sink.md` - source and sink data movement tutorial

## Suggested Learning Path

1. Read `docs/install/README.md` to choose an environment.
2. Follow `docs/tutorials/getting-started.md`.
3. Review `docs/connectors/README.md` for integration concepts.
4. Use `docs/connectors/source.md` and `docs/connectors/destinations.md` to map systems to connectors.
5. Read `docs/architecture.md` to understand platform components.
6. Follow `docs/tutorials/schema-registry.md` for governed events.
7. Follow `docs/tutorials/ksqldb.md` for streaming SQL workflows.
8. Follow `docs/tutorials/connect-source-to-sink.md` for integration patterns.
9. Use the install guides to decide how to run local, cloud, or OpenShift-based environments.

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