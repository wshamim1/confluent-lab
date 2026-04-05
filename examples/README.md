# Examples

This folder contains runnable or copy-ready assets that support the tutorials and architecture notes.

## Structure

- `connectors/` - connector configuration templates grouped into `source/` and `destinations/`
- `ksql/` - ksqlDB helper scripts and demo SQL
- `security/` - local security configuration examples for Kafka listeners, clients, and ACLs
- `schema-registry/` - Schema Registry helper scripts for listing subjects and registering sample schemas

The security examples also include local certificate-generation helpers and secured component config templates for Schema Registry and Kafka Connect.

## How To Use This Folder

- use `connectors/` when testing Kafka Connect APIs or building integration proof-of-concepts
- use `ksql/` with the ksqlDB tutorial for local stream-processing workflows
- use `schema-registry/` with the Schema Registry tutorial for contract registration and inspection

These files are starting points, not production-ready configurations.