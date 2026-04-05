# Customer 360 with CDC and Analytics

## Business Problem

Customer data is fragmented across CRM, support, billing, and product systems. Analytics and support teams need a near-real-time customer profile without constant batch reconciliation.

## Event-Driven Approach

Use CDC and SaaS integration to stream updates from source systems into Kafka, then create curated customer topics for downstream consumers.

Core topics:

- `crm.customers`
- `billing.accounts`
- `support.tickets`
- `product.usage-events`
- `customer360.profile-updates`

## Confluent Components

- Kafka brokers store the multi-system event history
- Schema Registry keeps customer identity and account schemas aligned
- Kafka Connect ingests database changes and SaaS records
- ksqlDB or stream applications join records into unified views

## Example Architecture

1. Debezium captures changes from CRM and billing databases.
2. Support and product events are ingested through connectors or application producers.
3. Identity resolution logic maps records to a common customer key.
4. A curated profile topic emits updates consumed by analytics, support, and marketing.
5. Sink connectors write the curated profile to warehouses and search systems.

## Topic Design

- use a durable canonical key such as `customer_id`
- preserve source-specific raw topics before creating curated topics
- keep profile update topics compacted if consumers need the latest view efficiently

## Connector Choices

Source:

- Debezium for CRM and billing databases
- SaaS source connectors where available
- object storage source for historical profile backfills

Destinations:

- warehouse sink for BI and modeling
- search sink for support portals
- downstream operational systems through JDBC or HTTP sink patterns

## Schema Guidance

- define clear ownership of the canonical customer schema
- separate source metadata from business fields
- version fields carefully because identity models are sticky and expensive to change later

## ksqlDB Opportunities

- create lightweight materialized views by customer segment
- track active ticket counts or usage thresholds per customer
- build derived streams for churn or upsell signals

## Operational Concerns

- identity resolution logic usually outgrows naive key joins
- privacy and access controls are central because customer data spans multiple systems
- compaction and retention settings must match profile and audit needs

## Why Kafka Fits

Kafka makes it possible to preserve source-level truth, build curated downstream views, and replay profile creation logic as customer models evolve.