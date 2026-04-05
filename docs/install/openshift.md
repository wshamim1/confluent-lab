# Installing Confluent Kafka on OpenShift

## Overview

OpenShift is a Kubernetes platform, so the practical way to run Confluent Kafka there is to deploy Confluent components as Kubernetes workloads and align them with OpenShift networking, security, and storage constraints.

In most cases, the cleanest path is:

1. Prepare an OpenShift cluster with suitable worker capacity and persistent storage.
2. Use a Kubernetes-native Confluent deployment approach.
3. Expose endpoints using OpenShift routes, load balancers, or internal services depending on access needs.

## When OpenShift Makes Sense

- your organization already standardizes on OpenShift
- platform governance, policy, and multi-tenancy are required
- you need Kubernetes-native deployment automation instead of VM-based operations

## What to Plan Before Installing

### Storage

- persistent volumes for broker data
- storage classes with predictable IOPS and latency
- enough capacity for retention, replication, and rebuild scenarios

### Networking

- internal broker-to-broker communication
- client ingress strategy for producers and consumers
- service exposure for Connect, Schema Registry, and operational tools

### Security

- service accounts and namespace isolation
- OpenShift security constraints and container permissions
- TLS certificates and secret management

### Operations

- monitoring and alerting
- rolling upgrade policy
- backup and disaster recovery design

## Typical Installation Pattern

### 1. Create a Project or Namespace

```bash
oc new-project confluent
```

### 2. Confirm Storage Classes

```bash
oc get storageclass
```

Choose a storage class suitable for stateful workloads before creating brokers.

### 3. Install the Kubernetes Operator or Control Plane Components

Use your organization's approved Confluent deployment method for Kubernetes. The exact steps vary by version and support policy, so verify the current supported installation path against your platform standards before rollout.

### 4. Create Stateful Platform Resources

Deploy at minimum:

- Kafka brokers and controllers
- Schema Registry if schemas are part of your contract model
- Kafka Connect if connectors are required
- optional operational UIs and metrics integrations

### 5. Expose Services

Depending on your network model, use:

- internal services for east-west traffic
- routes for HTTP-based services such as Schema Registry or Connect
- load balancers or ingress patterns for external Kafka clients

## OpenShift-Specific Considerations

### Security Contexts

OpenShift enforces stricter defaults than many plain Kubernetes environments. Validate that your container images, UID expectations, mounted volumes, and init behavior are compatible with your cluster security policy.

### Routes vs Kafka Protocol Access

OpenShift routes work well for HTTP services such as:

- Schema Registry
- Kafka Connect REST API
- Control Center

Kafka broker traffic is not ordinary HTTP traffic, so external access usually requires carefully designed listener exposure rather than a basic route.

### Operator Ownership

Decide early whether the Kafka platform team or the OpenShift platform team owns:

- cluster lifecycle
- secrets and certificates
- storage class selection
- upgrade scheduling

## Recommended Rollout Path

1. Start with a non-production OpenShift project.
2. Validate storage performance and client connectivity.
3. Enable Schema Registry and Connect only after the broker layer is stable.
4. Add monitoring, alerting, and backup workflows.
5. Run failure and upgrade rehearsals before production onboarding.

## When Not to Start Here

OpenShift is not the right first step if:

- the team is still learning Kafka basics
- you only need a laptop sandbox
- no one currently operates stateful platforms on Kubernetes well

In those cases, use local containers or Confluent Cloud first, then move to OpenShift once the data contracts and operating model are better defined.