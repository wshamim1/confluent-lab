# Local SASL_SSL Example

This example shows the shape of a secure local Kafka setup with:

- TLS for transport encryption
- SASL for client authentication
- ACL examples for authorization

## Files

- `broker.properties` - broker-side sample configuration
- `server_jaas.conf` - broker JAAS config for local SASL/PLAIN learning use
- `client.properties` - shared client config pattern for CLI producer and consumer tools
- `admin.properties` - admin client config for topic and ACL operations
- `generate-certs.sh` - creates local self-signed certificate and truststore assets for learning
- `schema-registry.properties` - sample Schema Registry configuration that connects to Kafka with `SASL_SSL`
- `connect-distributed.properties` - sample Kafka Connect worker configuration that connects to Kafka with `SASL_SSL`
- `ksqldb-server.properties` - sample ksqlDB server configuration that connects to Kafka with `SASL_SSL`
- `acl-examples.sh` - example ACL commands

## Scope

This example is designed for local understanding, not production rollout.

For production:

- use stronger secret handling
- consider SCRAM instead of PLAIN where appropriate
- rotate credentials and certificates properly
- secure related components such as Schema Registry, Connect, and ksqlDB separately

## Generated Assets

`generate-certs.sh` creates files under `certs/` for local testing:

- broker keystore
- broker truststore
- client truststore
- exported broker certificate

These are intentionally local-only artifacts and should not be treated as production certificate management.

## Docker Secure-Local Profile

This repository also includes a Docker secure-local startup path:

- `scripts/install/docker/docker-compose.secure-local.yml`
- `scripts/install/docker/up-secure.sh`
- `scripts/install/docker/down-secure.sh`

This path mounts the generated certs automatically and applies secure overrides for:

- Kafka broker
- Schema Registry
- Kafka Connect
- ksqlDB server