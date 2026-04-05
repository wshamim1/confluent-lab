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
- `acl-examples.sh` - example ACL commands

## Scope

This example is designed for local understanding, not production rollout.

For production:

- use stronger secret handling
- consider SCRAM instead of PLAIN where appropriate
- rotate credentials and certificates properly
- secure related components such as Schema Registry, Connect, and ksqlDB separately