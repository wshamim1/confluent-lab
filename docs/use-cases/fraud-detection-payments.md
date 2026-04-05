# Fraud Detection for Payments

## Business Problem

A payments platform must make near-real-time fraud decisions without slowing authorization paths or tightly coupling fraud logic to every payment microservice.

## Event-Driven Approach

Payment attempts, customer activity, device signals, and external fraud intelligence are streamed into Kafka. Fraud scoring services consume these events and emit decisions.

Core topics:

- `payments.authorizations.requested`
- `payments.authorizations.completed`
- `customer.login-events`
- `device.risk-signals`
- `fraud.decisions`

## Confluent Components

- Kafka brokers provide low-latency event delivery and replay
- Schema Registry keeps payment and risk event contracts stable
- Kafka Connect ingests third-party signals and exports fraud outcomes
- ksqlDB creates lightweight detection rules for velocity or threshold-based checks

## Example Architecture

1. Payment gateway publishes authorization requests.
2. Device fingerprint and customer login streams enrich context.
3. Fraud service consumes all related streams and computes a score.
4. Fraud decision topic publishes `approve`, `review`, or `block`.
5. Payment orchestration consumes the decision and completes workflow routing.

## Topic Design

- key payment events by `payment_id`
- key customer-centric topics by `customer_id` where customer history matters
- use separate topics for facts and decisions to keep auditability clean

## Connector Choices

Source:

- JDBC CDC from payments database
- HTTP or SaaS connector patterns for external fraud intelligence feeds
- object storage source for historical blacklists or watchlists

Destinations:

- warehouse sink for model training and investigation analytics
- Elasticsearch sink for fraud analyst dashboards
- JDBC sink for case management systems if needed

## Schema Guidance

- standardize timestamps, geolocation fields, currency, and merchant metadata
- preserve original authorization outcome separately from fraud decision outcome
- include trace or correlation identifiers across all related event families

## ksqlDB Opportunities

- detect repeated authorization attempts per card or customer in short windows
- compute rolling spend or velocity thresholds
- build live tables for high-risk merchants or regions

## Operational Concerns

- fraud pipelines must tolerate duplicate events and late arrivals
- retention must support audit and investigation requirements
- access control is stricter because payment data is highly sensitive

## Why Kafka Fits

Fraud detection requires multi-stream joins, replay, and decoupled consumption by scoring, analytics, and audit systems. Kafka supports all three cleanly.