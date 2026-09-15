# Kora — Confluent's Cloud-Native Kafka Engine

## Overview

**Kora** is the cloud-native engine that powers Confluent Cloud. It implements the **Apache Kafka protocol** on a completely re-engineered architecture designed for the cloud from the ground up.

Unlike a conventional Kafka deployment hosted in the cloud, Kora is not simply Kafka running on VMs. It is a purpose-built system that separates storage from compute, isolates tenants through a cell architecture, and manages all operational concerns — scaling, patching, durability, rebalancing — automatically.

Existing Kafka producers and consumers connect to Kora using the **standard Kafka protocol without modification**.

---

## The Four Outcomes of Kora

Kora's architecture is organized around four key outcomes:

| Outcome | What it means |
|---|---|
| **Low Latency** | Optimized data movement across memory, SSD, and object storage keeps hot data close to compute |
| **Elasticity** | Resources scale automatically within a capacity envelope — no broker management by customers |
| **Resilience** | 99.99% uptime SLA on dedicated and enterprise clusters, with proactive durability audits and automated recovery |
| **Cost Effectiveness** | Tiered storage and elastic scaling eliminate over-provisioning and reduce both infrastructure and operational spend |

---

## Low Latency

### Storage Hierarchy and Feedback Loops

Kora manages data across three storage tiers, driven by **real-time feedback loops** on cluster usage:

```
┌─────────────┐     ┌─────────────┐     ┌──────────────────────┐
│   Memory    │────▶│  Local SSD  │────▶│   Object Storage     │
│  (hottest)  │     │   (warm)    │     │  (cold / tiered)     │
└─────────────┘     └─────────────┘     └──────────────────────┘
      ▲                    ▲
      │                    └── SSD acts as a cache for recently tiered data
      └── Recently accessed data stays here for minimum latency
```

- **Hot data** (recently produced or frequently consumed) is kept in memory or on local SSD
- **Cold data** tiered to object storage is still cached on SSD for a period, balancing the cost of object store API calls against read latency
- The **broker mediates all access** to tiered data — this maximizes cache utility and minimizes per-request object store API costs

### Tail Latency Advantage

Average latency tells only part of the story. In production, **tail latency** (P99, P99.9) is what determines whether real-time applications remain responsive under load.

In Confluent benchmarking, Kora achieved up to **16x lower P99.9 end-to-end latency** than Apache Kafka at equivalent workloads.

| Percentile | What it reflects |
|---|---|
| P50 | Median — typical case |
| P95 | 1 in 20 requests is slower |
| P99 | 1 in 100 requests is slower |
| P99.9 | 1 in 1,000 requests is slower — the outliers that impact production |

While traditional Kafka latency increases significantly as workloads scale, Kora **maintains consistently low latency** because data placement is continuously optimized and hot data stays close to compute.

### Performance Characteristics

Kora's low-latency design has three properties that go beyond raw speed:

1. **Stable under heavy workloads** — performance does not degrade as throughput increases, unlike traditional Kafka deployments
2. **Resilient to infrastructure disruptions** — built-in monitoring, automated mitigation, and intelligent data placement prevent latency spikes during network or hardware events
3. **Continuously improving** — because Kora is a fully managed cloud service, Confluent rolls out performance optimizations, hardware tuning, and upgrades transparently, without customer intervention or downtime

---

## Elasticity

### How Traditional Kafka Scales

Apache Kafka capacity is **provisioned at deployment time** and scales through operator action — adding brokers, rebalancing partitions, and waiting for data to migrate. This process can take **over 40 hours** to add a single broker under realistic workloads.

### How Kora Scales

Customers do not provision brokers. Instead, they specify a **capacity envelope** expressed in workload dimensions:

- **Throughput** (MB/s in and out)
- **Storage** (GB retained)
- **Partitions** (count)

Kora scales physical resources within that envelope based on actual workload demand.

| Cluster Type | Scaling Model |
|---|---|
| **Standard** | Automatic within defined limits |
| **Enterprise** | Automatic elastic scaling — expands and contracts with demand |
| **Freight** | Automatic, optimized for high-throughput / cost |
| **Dedicated** | Manual scaling by changing CKU (Confluent Unit for Kafka) count; scaling operations are performed automatically |

The same scale-out operation that takes 40+ hours with open-source Kafka completes in **minutes** with Kora — up to **30x faster**.

### Benefits of Elastic Scaling

- **No over-provisioning** — capacity matches actual demand, eliminating wasted infrastructure spend
- **Scale up for peaks, down for troughs** — costs track usage rather than maximum possible load
- **No rebalancing delays or disruption** — scaling happens seamlessly, without the manual effort typically associated with Kafka broker management
- **Gbps-plus throughput** — clusters keep up with sudden traffic increases without performance bottlenecks

---

## Resilience

### The Problem with Self-Managed Kafka

Running Kafka in the cloud exposes teams to a range of failure modes that Kafka does not address out of the box:

- Infrastructure failures (VM crashes, disk failures)
- Network disruptions (packet loss, AZ-level events)
- Storage disruptions
- Errors during routine maintenance (patching, upgrades)
- Silent data corruption — Kafka has no native tooling to detect or recover from this

Addressing these gaps requires teams to configure cluster availability, design resiliency policies, implement disaster recovery and failover, monitor systems, and manage upgrades. This operational complexity diverts focus from building differentiated applications.

### The SLA Comparison

| Environment | Annual Uptime | Annual Downtime |
|---|---|---|
| Self-managed Kafka (~99%) | 99% | ~87.6 hours |
| Managed Kafka (99.9%) | 99.9% | ~8.76 hours |
| **Confluent Cloud (99.99%)** | **99.99%** | **~0.876 hours** |

Confluent Cloud delivers a **10x improvement** in availability over 99.9%, and up to **100x** compared to self-managed environments.

### What Kora's SLA Covers

Many providers only cover infrastructure availability. Confluent Cloud covers **all three layers**:

1. **Infrastructure** — cloud compute and storage
2. **Platform** — the Kora engine and its services
3. **Kafka software** — the Kafka protocol layer itself

This end-to-end coverage removes ambiguity: if your cluster is unavailable, it is covered — regardless of which layer caused the issue.

### Resilience Mechanisms

- **Proactive monitoring** — thousands of health probes continuously assess broker liveness, performance, and correctness
- **Automated recovery** — if a broker degrades, partition leadership is migrated away automatically; if degradation persists, the broker is replaced
- **Durability audits** — continuous verification that all stored data is retained for the required period and that no silent corruption has occurred
- **Fully managed maintenance** — deployment, optimization, upgrades, patching, and recovery are handled automatically; no manual effort required

### Cluster Linking for Geo-Replication

With a 99.99% SLA and **Cluster Linking**, organizations can enable seamless geo-replication across regions, ensuring data is always available and applications continue running even during regional disruptions.

---

## Cost Effectiveness (TCO)

Kora reduces **Total Cost of Ownership** across three dimensions:

### 1. Capacity Efficiency

Traditional Kafka environments require **over-provisioning for peak usage**, leading to wasted infrastructure spend during normal operation. Kora's elastic scaling means capacity closely tracks actual demand.

### 2. Operational Efficiency

Self-managed Kafka teams spend engineering time on:
- Capacity planning
- Broker scaling and rebalancing
- Networking and load balancing
- Patching and upgrades

With Kora, these tasks are automated. Engineering time is freed for building applications and driving business outcomes.

### 3. Storage Efficiency

Kora avoids the traditional tradeoff between performance and cost:

```
Hot data  ──▶  Local SSD   (fast, higher cost, small footprint)
Cold data ──▶  Object Store (slow, lower cost, large footprint)
```

Active data stays on fast disks. Cold data is offloaded to inexpensive object storage. The broker's tiered storage cache means cold data reads are still served locally most of the time, avoiding expensive object store API calls on every read.

---

## Cluster Types and Cost Alignment

| Cluster Type | Intended Use | Scaling |
|---|---|---|
| **Basic** | Experimentation, development, testing | Fixed |
| **Standard** | Production, public networking | Automatic |
| **Enterprise** | Production, private networking, elastic | Automatic elastic |
| **Freight** | High-throughput, cost-sensitive (logging, telemetry, monitoring) | Automatic |
| **Dedicated** | Isolated high-throughput production workloads | Manual CKU count |

Organizations can **mix and match** cluster types across teams and workloads, aligning cost, performance, and functionality to each specific use case.

---

## Kora Architecture Deep Dive

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CUSTOMERS / NETWORK LAYER                            │
│  VPC Peering · AWS PrivateLink · Azure PrivateLink · GCP Private Service    │
│  Connect · Terminates client connections · Rate limiting · Traffic routing  │
│                     (Stateless — scales independently)                      │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          COMPUTE LAYER                                      │
│                                                                             │
│  ┌─────────────────────────────┐   ┌─────────────────────────────────────┐ │
│  │          CELL A             │   │               CELL B                │ │
│  │  AZ-1 brokers               │   │  AZ-1 brokers                       │ │
│  │  AZ-2 brokers               │   │  AZ-2 brokers                       │ │
│  │  AZ-3 brokers               │   │  AZ-3 brokers                       │ │
│  │  (Tenant 1, Tenant 2 ...)   │   │  (Tenant 5, Tenant 6 ...)           │ │
│  └─────────────────────────────┘   └─────────────────────────────────────┘ │
│                                                                             │
│  Cluster Internal Services:                                                 │
│  • Data Balancing   • Health Checks   • Durability Audits   • Metadata(KRaft)│
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        OBJECT STORAGE LAYER                                 │
│        Cold data tiered to cloud object store (multi-AZ durable)           │
│        Minimizes inter-AZ data transfer costs                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       GLOBAL CONTROL PLANE                                  │
│  Orchestrates deployments across AWS · GCP · Azure                         │
│  Cluster Linking · Rolling fleet updates · Canary deployments              │
│  Exposes CKU and LKC abstractions to customers                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Network Layer

The networking layer is **stateless** — it handles:

- Diverse cloud networking technologies (VPC peering, AWS PrivateLink, Private NIC, Azure PrivateLink, Google Private Service Connect)
- Terminating client connections
- Applying rate limits
- Routing traffic to the appropriate physical cluster

Because it is stateless, it **scales independently of the brokers**. This is a significant departure from open-source Kafka, where each broker terminates client connections directly. In Kora, connection churn is absorbed by the routing layer, so brokers see a stable, multiplexed connection profile. This protects them from **connection storm pathologies** that can destabilize self-managed clusters.

### Cell Architecture

The **cell** is the foundational unit of physical isolation in Kora.

A physical Kafka cluster is divided into multiple cells. Each cell **cross-cuts all availability zones** — a single cell contains brokers in all three AZs to satisfy multi-AZ replication requirements.

A tenant (expressed as a logical Kafka cluster) is placed into a **single cell**. All replicas of that tenant's partitions reside on brokers within that cell. Inter-broker replication is confined within the cell.

#### Why Cells?

There is a fundamental trade-off in multi-tenant Kafka placement:

| Placement strategy | Problem |
|---|---|
| **Spread broadly across many brokers** | Writes become small, losing batched I/O efficiency. Blast radius of any failure is large — many customers affected simultaneously. |
| **Concentrated on few brokers** | A single broker failure removes a large fraction of capacity for that tenant. |

**Cells resolve this trade-off:**
- Within a cell, partition placement is dense enough to preserve I/O batching efficiency
- Across cells, blast radius is bounded — a failure in one cell affects only tenants resident in that cell

#### Linear Capacity Expansion

In a conventional Kafka cluster, adding brokers increases connection count and replication overhead **quadratically** — every client talks to every broker, and every broker may host follower replicas of partitions led elsewhere. This places a practical ceiling on cluster size.

Cells break this ceiling. Inter-broker replication is bounded within a cell, so **adding cells delivers linear capacity expansion**.

#### Tenant Placement Algorithm

Kora uses a **power-of-two-choices** algorithm for tenant placement:

1. When a new tenant is admitted, two cells are selected at random
2. The tenant is assigned to the cell with the lower current load

This dramatically improves load distribution over random placement with minimal coordination overhead and avoids hot-spotting.

#### Tenant Migration

When a cell approaches capacity, one or more tenants are moved to less-loaded cells. This cross-cell movement is enabled by the Kafka replication protocol's support for arbitrary member changes (analogous to Raft's joint consensus reconfiguration) — even when the source and destination broker sets are completely disjoint.

### Cluster Internal Services

| Service | Description |
|---|---|
| **Data Balancing** | A feedback loop driven by real-time cluster usage; continuously optimizes partition placement to balance CPU and local I/O while minimizing the cost and impact of movement |
| **Health Checks** | Thousands of probes that continuously assess broker liveness, performance, and correctness |
| **Storage Health Manager** | Tracks per-broker storage operations; if storage stops making progress, the broker is automatically restarted; if degradation persists, partition leadership is migrated away and the broker is replaced |
| **Durability Audits** | Continuous verification that all stored data is retained for the required period and that no silent corruption has occurred |
| **Metadata (KRaft)** | Runs on KRaft; architected for independent scaling from the broker fleet |

### Object Storage Layer

The object storage layer offloads cold data to cloud object storage. Brokers retain only the **working set**, which:

- Reduces replication overhead on hot brokers
- Minimizes inter-AZ data transfer costs (object store is natively multi-AZ durable)

### Global Control Plane

The global control plane is the orchestration brain of Confluent Cloud. It:

- Manages deployments across multiple regions and cloud providers (AWS, GCP, Azure)
- Coordinates operational services across all Confluent Cloud environments
- Supports multi-region data streaming through **Cluster Linking**
- Orchestrates rolling fleet updates through multi-phase deployment: performance tests → soak tests → live canary deployment
- Exposes the customer-facing **CKU** (Confluent Unit for Kafka) and **LKC** (Logical Kafka Cluster) abstractions that hide all underlying physical resources

---

## Kora vs Self-Managed Kafka — At a Glance

| Dimension | Self-Managed Apache Kafka | Kora (Confluent Cloud) |
|---|---|---|
| **Client connections** | Each broker terminates connections directly | Stateless network layer absorbs connection churn |
| **Scaling time** | 40+ hours to add a broker | Minutes (up to 30x faster) |
| **Broker management** | Customer provisions and manages brokers | No broker management — specify a capacity envelope |
| **Storage** | Single tier (local disk) | Three-tier: memory → SSD → object storage |
| **Tail latency** | Increases under load | Maintained — up to 16x lower P99.9 |
| **Multi-tenancy** | Manual isolation | Cell-based physical isolation |
| **Capacity expansion** | Quadratic overhead | Linear via cell addition |
| **Maintenance** | Customer responsibility | Fully managed — automated patching, upgrades, recovery |
| **Uptime SLA** | ~99% (infrastructure dependent) | 99.99% (infrastructure + platform + Kafka software) |
| **Data integrity** | No native corruption detection | Continuous durability audits |

---

## Summary

Kora is not Apache Kafka in the cloud — it is a re-engineered streaming engine that implements the Kafka protocol while solving the fundamental operational and architectural challenges of running Kafka at cloud scale.

Its four design outcomes — **low latency, elasticity, resilience, and cost effectiveness** — are delivered through:

- A **tiered storage hierarchy** driven by real-time feedback loops
- A **stateless network layer** that decouples connection handling from broker compute
- A **cell architecture** that provides physical isolation, bounds blast radius, and enables linear capacity scaling
- **Automated cluster internal services** (data balancing, health checks, durability audits) that eliminate operational toil
- A **global control plane** that orchestrates the entire fleet across regions and cloud providers

The result is predictable, low-latency, continuously improving performance at scale — without customers managing a single broker.
