# Install Scripts

This folder contains setup assets for local and cluster-oriented Confluent Kafka environments.

## Structure

- `docker/` - Docker Compose definitions and helper scripts
- `podman/` - Podman Compose definitions and helper scripts
- `kubernetes/` - Kubernetes and OpenShift bootstrap assets

Docker also includes a secure-local override path for the local security example.

## Intended Use

- use `docker/` when the local environment is Docker-based
- use `podman/` when the local environment is Podman-based
- use `kubernetes/` when preparing OpenShift or Kubernetes namespaces and prerequisites

The install guides in `docs/install/` explain when to use each path.