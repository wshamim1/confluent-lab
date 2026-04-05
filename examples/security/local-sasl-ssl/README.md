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