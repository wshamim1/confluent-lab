# IoT Predictive Maintenance

## Business Problem

An industrial manufacturer collects telemetry from machines across factories and wants to predict failures before unplanned downtime occurs.

## Event-Driven Approach

Sensors continuously emit temperature, vibration, pressure, and runtime events. These are streamed into Kafka, enriched with asset metadata, and used for alerting and maintenance planning.

Core topics:

- `telemetry.raw`
- `telemetry.normalized`
- `assets.metadata`
- `maintenance.alerts`
- `maintenance.work-orders`

## Confluent Components

- Kafka brokers ingest high-volume telemetry streams
- Schema Registry controls device payload evolution across firmware versions
- Connect ingests from MQTT or edge gateways and sinks alerts into ticketing systems
- ksqlDB or stream processors derive anomaly windows and threshold breaches

## Example Architecture

1. Edge gateway or MQTT connector publishes raw telemetry.
2. Normalization service converts vendor-specific payloads into standard schemas.
3. Stream processing enriches telemetry with asset registry data.
4. Alert rules generate events when readings exceed thresholds or patterns show degradation.
5. Sink connectors push alerts to maintenance systems and data lakes.

## Topic Design

- key by `device_id` or `asset_id`
- separate raw ingestion topics from normalized topics
- use retention tiers: short for noisy raw topics, longer for normalized or alert topics

## Connector Choices

Source:

- MQTT source for edge and device traffic
- JDBC or CDC source for asset master data

Destinations:

- S3 sink for historical telemetry analysis
- JDBC or HTTP sinks for maintenance systems
- search sinks for operations dashboards

## Schema Guidance

- define units explicitly for every measurement
- include firmware version and site identifier
- use optional fields for device-specific extensions without breaking the common contract

## ksqlDB Opportunities

- moving averages over sensor windows
- threshold-based alerting per site or machine type
- derived tables of active incidents by factory

## Operational Concerns

- telemetry volumes can be very high, so partitioning and retention matter early
- edge disconnections create bursty catch-up traffic
- some use cases need exactly-once downstream behavior for alert generation

## Why Kafka Fits

Kafka handles high-throughput ingestion, replayable operational history, and multiple downstream consumers without forcing edge systems to integrate directly with each target.