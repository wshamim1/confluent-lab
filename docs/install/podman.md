# Running Confluent Kafka with Podman

## Overview

Podman is a practical alternative to Docker for running the local Confluent lab. In many cases, you can use the existing compose file in this repo with only minor adjustments.

## Best Fit

Use Podman when:

- your workstation standard is Podman rather than Docker
- you want a daemonless local container runtime
- you are working in Linux-first or Red Hat-oriented environments

## Prerequisites

- Podman 4.x or newer
- `podman compose` support, or the `podman-compose` package
- at least 8 GB RAM available for the full local stack

Verify the runtime:

```bash
podman --version
podman compose version
```

## Start the Stack

Podman assets live in `scripts/install/podman/`.

From that directory:

```bash
cd scripts/install/podman
podman compose up -d
```

Check service status:

```bash
podman compose ps
```

## Network Notes

The compose file exposes the same host ports used in the Docker workflow:

- `9092` for Kafka
- `8081` for Schema Registry
- `8083` for Connect
- `9021` for Control Center

If those ports are already occupied, change the host-side mappings in your Compose definition.

Related example assets:

- `examples/ksql/` for generic ksqlDB scripts that can run with Podman
- `examples/schema-registry/` for Schema Registry helper scripts
- `examples/connectors/` for connector templates

## Rootless Caveats

When running Podman rootless:

- port publishing usually works for these non-privileged ports
- volume ownership can behave differently than Docker on macOS and Linux
- network behavior may differ slightly depending on Podman machine configuration

If networking behaves unexpectedly on macOS:

1. Inspect `podman machine ls`.
2. Ensure the VM is running.
3. Retry with a clean environment using `podman compose down -v` and `podman compose up -d`.

## Useful Commands

Show logs:

```bash
podman compose logs broker
podman compose logs connect
```

Open a shell in the broker container:

```bash
podman exec -it broker bash
```

Stop and remove the stack:

```bash
podman compose down -v
```

## Validation

Once the stack is up, validate it with client or console tooling:

1. List topics.
2. Produce a few records.
3. Consume them back.
4. Open `http://localhost:9021` if Control Center is enabled.

You can also use the ksqlDB helpers from `examples/ksql/` after the stack is running.

## Caveat About Connector Plugins

The base Connect image includes the runtime, but not every external connector plugin you may want. For JDBC, S3, Debezium, and other connectors, you may need to extend the image or install plugins before creating connectors.