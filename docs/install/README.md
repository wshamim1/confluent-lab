# Installation Guides

This folder contains installation and deployment guidance for Confluent Kafka in different environments.

Related repository paths:

- `scripts/install/` - runtime-specific setup assets
- `examples/` - example connector, Schema Registry, and ksqlDB assets used by tutorials

## Guides

- `options.md` - choose between Confluent Cloud, local containers, and self-managed deployment
- `podman.md` - run the local lab with Podman and Podman Compose
- `openshift.md` - deploy Confluent Kafka on OpenShift-oriented Kubernetes environments

## Which Guide to Start With

Start with `options.md` if you are still deciding where Kafka should run.

Use `podman.md` if:

- Docker Desktop is not available
- you prefer daemonless local containers
- you are testing on Fedora, RHEL, or Podman-based workstations

Use `openshift.md` if:

- your target platform is OpenShift
- you need Kubernetes-native deployment planning
- you are evaluating Confluent for Kubernetes in enterprise clusters

For concrete setup files, start in `scripts/install/README.md` after choosing a deployment path.