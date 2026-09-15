# Confluent Data Streaming Platform (DSP) — Introduction

## Prerequisites

No prior Kafka or Flink experience is required. Familiarity with the following concepts will help:

- **Event** — a record of something that happened, e.g. a payment was made, a sensor reading was taken
- **Message broker** — a system that receives, stores, and delivers messages between producers and consumers
- **Batch processing** — processing data in scheduled chunks (hourly, nightly)
- **Stream processing** — processing data continuously as it arrives

---

## Key Concepts Glossary

| Term | Definition |
|---|---|
| **Topic** | A named, durable log in Kafka where events are written and read. Topics are the central unit of storage in the DSP. |
| **Partition** | A topic is split into partitions for parallelism. Each partition is an ordered, immutable sequence of events. |
| **Offset** | A sequential ID for each event within a partition. Consumers track their position using offsets. |
| **Producer** | An application that writes events to a Kafka topic. |
| **Consumer** | An application that reads events from a Kafka topic. |
| **Consumer Group** | A set of consumers that share the work of reading a topic. Each partition is read by only one consumer in the group at a time. |
| **Schema** | The structure definition of an event (field names, types, required/optional). Managed by Schema Registry. |
| **Connector** | A pre-built integration that moves data between Kafka and an external system (database, SaaS, etc.). |
| **Stream** | An unbounded, continuously updating sequence of events. |
| **Table** | A view of a stream representing the latest state per key (e.g. the current balance for each account). |
| **Watermark** | A marker in a Flink stream that signals all events up to a certain timestamp have been received, used to trigger time-based operations. |
| **Kora** | Confluent's cloud-native Kafka engine that separates storage and compute for elastic scaling. |
| **MCP** | Model Context Protocol — an open protocol for exposing real-time context to AI agents and LLMs. |

---

## Batch vs Streaming — Why DSP?

Traditional architectures rely on **batch processing**: data is collected, stored, and then processed on a schedule (hourly, nightly, etc.). This introduces latency between when something happens and when the business can act on it.

| | Batch | Streaming |
|---|---|---|
| **When data is processed** | On a schedule | As events occur |
| **Latency** | Minutes to hours | Milliseconds to seconds |
| **Data freshness** | Stale by design | Always current |
| **Failure recovery** | Re-run the batch | Replay from Kafka offset |
| **Use cases** | End-of-day reports, billing runs | Fraud detection, real-time recommendations, predictive maintenance |

The DSP eliminates the batch boundary. Events are processed **in motion** — the moment a sensor fires, a payment clears, or a shipment moves, downstream systems can react immediately.

---

## Overview

This tutorial introduces the **Confluent Data Streaming Platform (DSP)** at the component architecture level. Confluent provides a unified platform for **connecting, streaming, processing, governing, and serving data in real-time** across hybrid and multi-cloud environments.

Built on **Apache Kafka** and **Apache Flink**, the platform enables organizations to move and act on data as events happen — rather than relying on batch processes.

The platform combines:

- **Data Streaming** — powered by Apache Kafka
- **Stream Processing** — powered by Apache Flink
- **Governance** — Schema Registry, Stream Catalog, Stream Lineage, Stream Quality
- **Open Table Integration** — through TableFlow (Apache Iceberg / Delta Lake)
- **AI Capabilities** — through Confluent Intelligence

Together, these services help organizations create **trusted, reusable real-time data products** that power applications, analytics, and AI.

---

## The Six Pillars of the DSP

The Confluent Data Streaming Platform is organized into **six pillars**, each addressing a specific stage of the data streaming lifecycle while working together through Kafka topics, schemas, and shared metadata.

```
┌───────────┐   ┌───────────┐   ┌───────────┐   ┌────────────┐   ┌──────────────┐   ┌─────────────┐
│  Connect  │──▶│  Stream   │──▶│  Process  │──▶│   Govern   │──▶│  TableFlow   │──▶│ Intelligence│
└───────────┘   └───────────┘   └───────────┘   └────────────┘   └──────────────┘   └─────────────┘
```

---

### 1. Stream

**Stream** is the foundation of the platform. It delivers **Apache Kafka** as:

- A **fully managed cloud service** through Confluent Cloud
- **Self-managed software** through Confluent Platform

In Confluent Cloud, Kafka is powered by **Kora** — Confluent's cloud-native streaming engine — which separates storage and compute to provide:

- Elastic scaling
- High availability
- Fully managed operations

#### Confluent Cloud Cluster Types

| Cluster Type | Use Case |
|---|---|
| **Basic** | Development and testing |
| **Standard** | General production workloads |
| **Enterprise** | Enterprise networking requirements |
| **Freight** | High-throughput workloads |
| **Dedicated** | Isolated single-tenant clusters |

Applications connect using the **standard Kafka protocol**, meaning existing Kafka clients work without modification.

---

### 2. Connect

**Connect** integrates Kafka with the broader data ecosystem. Confluent provides a large catalog of **source and sink connectors** that stream data between Kafka and:

- Databases
- SaaS applications
- Data warehouses
- Object stores
- Messaging systems

Connectors can be **fully managed by Confluent** or operated by customers, reducing the effort required to build and maintain integrations.

---

### 3. Govern

**Govern** ensures that streaming data remains **trusted, discoverable, and compliant**. The fully managed governance suite includes:

| Capability | Description |
|---|---|
| **Schema Registry** | Manages event schemas and enforces schema compatibility |
| **Stream Catalog** | Data discovery and business metadata |
| **Stream Lineage** | Visualizes data flows from ingestion to analytics |
| **Stream Quality** | Enforces data contracts and quality standards |

This is particularly valuable in regulated industries like **financial services**, where transaction data must be auditable at every stage.

---

### 4. Process

**Process** is powered by **Apache Flink**. Confluent Cloud for Apache Flink enables organizations to:

- **Filter** — remove unwanted events
- **Enrich** — add context from other sources
- **Join** — combine streams and tables
- **Aggregate** — compute running totals, counts, averages
- **Transform** — reshape events as they occur

By processing data **in motion**, teams create reusable data products and deliver insights to applications and analytic systems with minimal latency.

Key benefits:
- Mainframe events and cloud-native applications can coexist within the same framework
- Eliminates redundant pipelines and reduces data silos
- Downstream applications receive consistent, enriched information
- Accelerates innovation by eliminating repeated reprocessing for different use cases

---

### 5. TableFlow

**TableFlow** extends streaming data into analytical ecosystems by continuously materializing Kafka topics as **Apache Iceberg** or **Delta Lake** tables.

TableFlow automatically handles:

- Schema evolution
- Type conversions
- Catalog integration
- Table maintenance

This makes **real-time operational data immediately available** to analytics and AI workloads without building custom data pipelines.

---

### 6. Intelligence

**Confluent Intelligence** brings AI capabilities directly into the streaming platform. It consists of four core components:

| Component | Description |
|---|---|
| **AI and ML Functions** | Model inference directly within Flink pipelines |
| **Streaming Agents** | Event-driven agentic workflows that react to business events in real-time |
| **Real-Time Context Engine** | Provides governed real-time context to AI applications and agents via MCP |
| **MCP Server for Confluent Cloud** | Enables AI-driven management and operation of the platform itself |

Together, these capabilities help organizations build **AI systems that operate on trusted real-time data** rather than static snapshots.

---

## End-to-End Data Flow

The diagram below illustrates how all six pillars work together in practice, from event producers on the left to AI and analytics consumers on the right.

```
Event Producers
     │
     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         CONNECT                                          │
│  Databases · SaaS · Enterprise Apps · Messaging Systems · Object Stores │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    STREAM (Apache Kafka)                                  │
│  Accounts · Purchases · Payments · Shipments · Click Streams            │
│            Durable · Scalable · Reusable Source of Truth                │
└──────────┬───────────────────────────────────────────────┬──────────────┘
           │                                               │
           ▼                                               ▼
┌────────────────────────────┐             ┌───────────────────────────────┐
│   PROCESS (Apache Flink)   │             │           GOVERN               │
│  Filter · Enrich · Join    │             │  Schema Registry               │
│  Aggregate · Transform     │             │  Stream Catalog                │
│  ML Functions              │             │  Stream Lineage                │
│  Streaming Agents          │             │  Stream Quality                │
└────────────────────────────┘             └───────────────────────────────┘
           │
     ┌─────┼──────────────────────────┐
     │     │                          │
     ▼     ▼                          ▼
┌─────────────┐  ┌───────────────┐  ┌──────────────────────────┐
│  TABLEFLOW  │  │ INTELLIGENCE  │  │   Applications &          │
│             │  │               │  │   Microservices           │
│  Iceberg /  │  │  Real-Time    │  │                           │
│  Delta Lake │  │  Context      │  │   (consume directly from  │
│             │  │  Engine (MCP) │  │    Kafka topics)          │
└──────┬──────┘  └──────┬────────┘  └──────────────────────────┘
       │                │
       ▼                ▼
┌──────────────┐  ┌─────────────────────────────────┐
│  Analytics   │  │  AI Applications · LLMs · Agents│
│  Engines /   │  │  (fresh context via MCP,        │
│  Data        │  │   not stale snapshots)           │
│  Lakehouses  │  └─────────────────────────────────┘
└──────────────┘
```

**Key takeaway:** Applications, analytics platforms, and AI systems all consume the same **governed real-time data foundation**. Rather than creating separate architectures for operational systems, analytics, and AI — organizations **build once** on the DSP and serve multiple use cases from a **single source of truth**.

---

## Kafka vs Flink — When to Use Which

A common source of confusion: Kafka and Flink are both part of the DSP but serve fundamentally different roles.

| | Apache Kafka (Stream) | Apache Flink (Process) |
|---|---|---|
| **Role** | Store and transport events | Transform and compute on events |
| **Analogy** | A durable, replayable event log | A real-time computation engine reading from that log |
| **Persistence** | Events are retained for a configurable period (hours to forever) | Flink is stateful but not the system of record |
| **Primary operations** | Produce, consume, replay | Filter, join, aggregate, enrich, infer |
| **SQL support** | Kafka topics can be queried via ksqlDB | Flink SQL is a full streaming SQL dialect |
| **Scaling unit** | Partitions | Parallelism slots |
| **When to use** | Any time you need durable, replayable, shared event transport | When you need to compute something new from the stream — a derived topic, an alert, a joined view |

**The key rule:** Kafka is where data *lives*. Flink is where data *becomes something useful*. They work together — Flink reads from Kafka topics and typically writes its output back to new Kafka topics, which other consumers then read.

```
Kafka Topic A ──▶ Flink Job (join + enrich) ──▶ Kafka Topic B ──▶ Applications / TableFlow / AI
```

---

## Confluent Cloud vs Confluent Platform

The DSP is available in two deployment modes. The six pillars are the same; the operational model differs.

| | Confluent Cloud | Confluent Platform |
|---|---|---|
| **Deployment** | Fully managed SaaS (AWS, GCP, Azure) | Self-managed on-prem or private cloud |
| **Kafka engine** | Kora (storage/compute separated) | Standard Apache Kafka |
| **Operations** | Confluent manages upgrades, scaling, availability | Customer manages infrastructure |
| **Cluster types** | Basic, Standard, Enterprise, Freight, Dedicated | Single cluster type, sized manually |
| **Networking** | Public, Private Link, VPC peering | Directly controlled |
| **Best for** | Teams wanting low operational overhead | Organizations with data residency or air-gap requirements |
| **Flink** | Confluent Cloud for Apache Flink (fully managed) | Self-managed Flink on Kubernetes |
| **Governance** | Fully managed Stream Governance suite | Confluent Control Center + Schema Registry |

Both modes expose the **standard Apache Kafka protocol**, so producers and consumers work identically regardless of deployment.

---

## Common Misconceptions

### "Kafka is just a message queue"

Kafka is fundamentally different from traditional queues (RabbitMQ, IBM MQ, SQS). In a queue, messages are deleted after consumption. In Kafka:
- Events are **retained** on disk for a configurable period (days, weeks, or indefinitely)
- **Multiple independent consumers** can all read the same events without interfering with each other
- Consumers can **replay** past events by resetting their offset
- This makes Kafka a **replayable, shared event log** — not a queue

### "Real-time means zero latency"

Real-time in the DSP context means **sub-second to low-second latency** — fast enough that applications and users perceive results as immediate. It does not mean zero latency. Typical end-to-end latency (produce → Flink process → consume) is **10ms–500ms** depending on configuration.

### "You need Flink for everything"

Simple event routing and filtering can be done with **Kafka Streams or ksqlDB** without Flink. Flink is best suited for:
- Complex stateful operations (joins across multiple streams, aggregations over time windows)
- ML inference embedded in the pipeline
- Long-running streaming jobs with exactly-once guarantees

### "TableFlow replaces your data warehouse"

TableFlow materializes Kafka topics as open table format files (Iceberg/Delta Lake). It makes streaming data *available to* analytics engines — it does not replace them. Your data warehouse or lakehouse query engine (Snowflake, Databricks, Trino, etc.) still runs the queries; TableFlow just ensures the tables are always fresh.

### "Governance is only for compliance teams"

Schema Registry and Stream Lineage are equally valuable for developers. Schema Registry prevents breaking schema changes from silently corrupting downstream consumers. Stream Lineage helps debug where bad data entered the pipeline. Governance is an operational tool, not just a regulatory checkbox.

---

## Governance Deep Dive

A key challenge for any data platform is ensuring streaming data is both **reliable and actionable** in real-time. The Confluent DSP addresses this with a fully managed governance suite:

- **Schema compatibility enforcement** prevents breaking changes from reaching consumers
- **Stream lineage** tracks data flows from ingestion to analytics, ensuring accuracy and compliance
- **Data contracts** enforced through Stream Quality ensure consistent data shapes across producers and consumers

The integration of governance, process, and intelligence creates a **composable architecture** where data streams remain trusted and accessible across the enterprise. This reduces bottlenecks and accelerates development cycles.

---

## Confluent Intelligence Deep Dive

### AI and ML Functions
Allow model inference **directly within Flink pipelines** — no need to export data before running inference.

### Streaming Agents
Enable **event-driven agentic workflows** that react to business events in real-time, automating responses as they happen.

### Real-Time Context Engine
Provides **governed real-time context** to AI applications and agents through the **Model Context Protocol (MCP)**. AI systems retrieve fresh business context without requiring direct Kafka access, ensuring decisions are based on current trusted information rather than stale snapshots.

### MCP Server for Confluent Cloud
Exposes platform operations through MCP, enabling AI assistants and agents to:
- Monitor streaming infrastructure
- Manage topics, connectors, and schemas
- Troubleshoot issues
- Automate platform operations through natural language workflows

---

## Summary

| Pillar | Technology | Primary Purpose |
|---|---|---|
| **Stream** | Apache Kafka (Kora) | Durable, scalable event streaming backbone |
| **Connect** | Managed Connectors | Integrate Kafka with the broader ecosystem |
| **Govern** | Schema Registry, Catalog, Lineage, Quality | Trusted, discoverable, compliant data |
| **Process** | Apache Flink | Real-time filtering, enrichment, transformation |
| **TableFlow** | Apache Iceberg / Delta Lake | Bridge streaming to analytics lakehouses |
| **Intelligence** | AI/ML Functions, Agents, MCP | Context-aware AI on real-time data |

Together, these six pillars form an integrated data streaming platform that enables organizations to:

1. **Connect** systems across hybrid and multi-cloud environments
2. **Govern** data to ensure trust and compliance
3. **Process** events in real-time with minimal latency
4. **Support analytics** through open table formats
5. **Power AI applications** using a shared stream of trusted business events
