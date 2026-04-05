# Tutorial: Schema Registry Workflow

## Goal

Understand how Schema Registry helps producers and consumers evolve event contracts safely.

## Local Scripts

This repository includes helper scripts for local Schema Registry workflows:

- `schema-registry-examples/schema-registry-list-subjects.sh`
- `schema-registry-examples/schema-registry-register-order-schema.sh`

These scripts are runtime-agnostic because they call the local Schema Registry HTTP API directly.

## Why Use Schema Registry

Without schema governance, event formats drift over time and break downstream consumers. Schema Registry centralizes schema versions and compatibility policies.

## Supported Schema Types

- Avro
- Protobuf
- JSON Schema

## Subject Naming Basics

Common patterns include:

- topic-based subjects such as `orders.created-value`
- record-based subjects in more advanced multi-topic patterns

## Compatibility Modes

- `BACKWARD`: new consumers can read older data
- `FORWARD`: older consumers can read newer data under defined constraints
- `FULL`: both backward and forward compatibility expectations
- transitive variants apply checks across more than the latest version

## Example Event Evolution

Initial schema:

```json
{
  "type": "record",
  "name": "OrderCreated",
  "fields": [
    {"name": "order_id", "type": "string"},
    {"name": "customer_id", "type": "string"},
    {"name": "total_amount", "type": "double"}
  ]
}
```

Backward-compatible change:

```json
{
  "type": "record",
  "name": "OrderCreated",
  "fields": [
    {"name": "order_id", "type": "string"},
    {"name": "customer_id", "type": "string"},
    {"name": "total_amount", "type": "double"},
    {"name": "currency", "type": "string", "default": "USD"}
  ]
}
```

The new field includes a default, so older records remain readable.

## Interacting with Schema Registry

List subjects with the helper script:

```bash
./schema-registry-examples/schema-registry-list-subjects.sh
```

Get subjects:

```bash
curl http://localhost:8081/subjects
```

Get versions for a subject:

```bash
curl http://localhost:8081/subjects/orders.created-value/versions
```

Check compatibility:

```bash
curl -X POST http://localhost:8081/compatibility/subjects/orders.created-value/versions/latest \
  -H 'Content-Type: application/vnd.schemaregistry.v1+json' \
  -d '{"schema": "{\"type\":\"record\",\"name\":\"OrderCreated\",\"fields\":[{\"name\":\"order_id\",\"type\":\"string\"},{\"name\":\"customer_id\",\"type\":\"string\"},{\"name\":\"total_amount\",\"type\":\"double\"},{\"name\":\"currency\",\"type\":\"string\",\"default\":\"USD\"}]}"}'
```

Register the sample schema with the helper script:

```bash
./schema-registry-examples/schema-registry-register-order-schema.sh
```

## Practical Guidance

- define schemas before many teams begin publishing to the topic
- choose compatibility mode deliberately by data contract type
- avoid using schema changes to hide domain ambiguity
- treat schemas as part of the API of your event platform

## Production Considerations

- protect Schema Registry with authentication and TLS
- back up or replicate metadata according to platform requirements
- include schema validation in CI when schemas are managed in Git

## Next Step

Use connectors with governed serialization so source systems, Kafka topics, and downstream consumers all share compatible contracts.