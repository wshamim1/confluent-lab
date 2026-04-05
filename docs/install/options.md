# Confluent Kafka Installation Options

## Overview

There is no single best installation path. The right option depends on whether you are optimizing for speed, control, cost, or compliance.

## Option 1: Confluent Cloud

Best for:

- teams that want the fastest path to production
- organizations without dedicated Kafka platform operators
- workloads that benefit from managed scaling and managed connectors

What you get:

- managed Kafka clusters
- managed connectors
- Schema Registry and governance features
- operational tooling without running brokers yourself

Tradeoffs:

- less low-level infrastructure control
- pricing may exceed self-managed cost at some scales or usage patterns
- some teams need private networking or compliance setup before adoption

Typical setup flow:

1. Create a Confluent Cloud environment.
2. Create a Kafka cluster.
3. Create API keys.
4. Create topics and optionally Schema Registry.
5. Connect apps or managed connectors.

## Option 2: Local Containers

Best for:

- learning and tutorials
- local application development
- integration smoke tests

What you get:

- quick startup on a laptop
- disposable environment
- easy access to Control Center and Connect APIs

Tradeoffs:

- not production-grade
- single-host failure domain
- resource limits on developer machines

Available local container paths in this repo:

- Docker-based local evaluation
- Podman-based local evaluation using the notes in `podman.md`

Useful endpoints in the sample stack:

- Kafka broker: `localhost:9092`
- Schema Registry: `http://localhost:8081`
- Kafka Connect: `http://localhost:8083`
- Control Center: `http://localhost:9021`

## Option 3: Confluent Platform Self-Managed

Best for:

- teams with strict compliance, residency, or network constraints
- platforms that need deep operational control
- hybrid or on-prem environments

What you manage:

- brokers and controller nodes
- storage and networking
- monitoring, backups, upgrades, and security hardening
- Connect workers, Schema Registry, and optional Control Center

Tradeoffs:

- highest operational burden
- requires capacity planning and upgrade discipline
- incident response and scaling are your responsibility

Common deployment targets:

- virtual machines
- bare metal
- Kubernetes via operators or Helm-based patterns
- OpenShift via Kubernetes-native deployment patterns

## Option 4: Kubernetes and OpenShift

Best for:

- teams already standardized on Kubernetes operations
- environments where automation and declarative operations matter
- enterprise clusters with policy enforcement and controlled multi-tenancy

What to plan for:

- stable storage classes
- pod disruption handling
- network policies and service exposure
- observability and rolling upgrades
- security context constraints and route or ingress exposure on OpenShift

Tradeoffs:

- more moving parts than local Compose environments
- easier automation, but also easier to build fragile clusters if storage and networking are not designed carefully

For OpenShift-specific considerations, continue with `openshift.md`.

## Decision Guide

Choose Confluent Cloud when:

- time to value matters most
- managed connectors are attractive
- your team is application-heavy and operations-light

Choose local containers when:

- you need a disposable sandbox
- you are learning or validating examples

Choose self-managed when:

- infrastructure control is mandatory
- you already operate distributed stateful systems well

Choose Kubernetes or OpenShift when:

- your organization already runs stateful platforms on Kubernetes successfully
- platform standardization matters more than minimum setup complexity

## Minimum Local Prerequisites

- Docker Desktop or a compatible Docker engine, or Podman 4+
- at least 8 GB RAM recommended for the full local stack
- Python 3.10+ for the included examples

## Installation Strategy by Maturity

### Individual Learning

- use Docker Compose or Podman Compose
- run the Python examples
- experiment with connector REST APIs

### Team Prototype

- start in Confluent Cloud or shared container-based dev infrastructure
- define topic naming and schema rules early

### Production Rollout

- choose Cloud unless there is a strong reason not to
- if self-managed, define SLOs, backup strategy, upgrade process, and capacity model before onboarding product teams