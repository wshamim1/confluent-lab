# Real-World Confluent Kafka Use Cases

This folder contains practical, production-oriented Confluent Kafka scenarios. Each use case focuses on a different business domain and shows how Kafka, Schema Registry, Kafka Connect, and ksqlDB fit together.

## Use Cases

- `retail-order-lifecycle.md` - order, payment, inventory, and fulfillment event flow
- `fraud-detection-payments.md` - real-time payment risk detection and decisioning
- `iot-predictive-maintenance.md` - device telemetry ingestion and maintenance alerts
- `customer-360-cdc-analytics.md` - CDC-driven customer profile and analytics pipelines
- `logistics-shipment-tracking.md` - shipment status streaming across carriers and warehouses

## How To Read These

For each use case, look at:

- business problem
- event flow
- topic design
- connector choices
- schema guidance
- ksqlDB or stream processing opportunities
- operational concerns

These are templates for architecture thinking, not one-size-fits-all designs.