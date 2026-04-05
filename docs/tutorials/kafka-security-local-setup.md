# Tutorial: Local Kafka Security Setup

## Goal

Use a concrete local example to understand how secure Kafka configuration fits together across broker properties, client properties, TLS trust, SASL credentials, and ACLs.

## Example Location

The local example files live in:

- `examples/security/local-sasl-ssl/`

Main files:

- `broker.properties`
- `server_jaas.conf`
- `client.properties`
- `admin.properties`
- `generate-certs.sh`
- `schema-registry.properties`
- `connect-distributed.properties`
- `acl-examples.sh`

## What This Example Demonstrates

- encrypted client-to-broker traffic with `SASL_SSL`
- simple local authentication with SASL/PLAIN
- separate admin and application principals
- ACL-based authorization examples

## Important Scope Warning

This is a local learning example.

It is intentionally simpler than production setups:

- SASL/PLAIN is used because it is easier to understand locally
- certificate generation is local and self-signed for learning
- related services are shown with sample secure Kafka client configs, not full production hardening

For production, use a stronger approved model such as SCRAM or mTLS where appropriate.

## Step 1: Review the Broker Configuration

Open `examples/security/local-sasl-ssl/broker.properties`.

Notice these key areas:

- listener uses `SASL_SSL`
- TLS keystore and truststore locations are defined
- SASL/PLAIN is enabled
- authorizer is enabled
- `allow.everyone.if.no.acl.found=false` prevents implicit open access

## Step 2: Generate Local Certificate Assets

Run:

```bash
./examples/security/local-sasl-ssl/generate-certs.sh
```

This generates local keystore and truststore files under `examples/security/local-sasl-ssl/certs/`.

You still need to place or mount them where your broker and clients expect them.

## Step 3: Review the Broker JAAS File

Open `examples/security/local-sasl-ssl/server_jaas.conf`.

This file shows example local users:

- `broker`
- `admin`
- `appuser`

For local learning, this makes the principal model easy to see.

## Step 4: Review Client Configuration

Open `examples/security/local-sasl-ssl/client.properties`.

This file shows the minimum client-side ideas:

- connect to the secure listener
- trust the broker certificate
- authenticate with SASL credentials

Use the admin client separately via `admin.properties` so operational permissions do not get mixed into application clients.

## Step 5: Review Secured Schema Registry and Connect Examples

Open:

- `examples/security/local-sasl-ssl/schema-registry.properties`
- `examples/security/local-sasl-ssl/connect-distributed.properties`

These show how adjacent Confluent components can connect to Kafka with:

- `security.protocol=SASL_SSL`
- matching SASL mechanism
- truststore configuration

This is the important extension of Kafka security: brokers are only part of the overall platform.

## Step 6: Create Topics Using the Admin Client

Example:

```bash
kafka-topics --bootstrap-server localhost:9093 --command-config examples/security/local-sasl-ssl/admin.properties --create --topic orders.created --partitions 3 --replication-factor 1
```

## Step 7: Apply ACLs

Review `examples/security/local-sasl-ssl/acl-examples.sh`.

It shows how to grant:

- write access to a topic
- read access to a topic
- read access to a consumer group

Important point:

- consumers often need both topic and group permissions

## Step 8: Test a Producer

Example:

```bash
kafka-console-producer --bootstrap-server localhost:9093 --producer.config examples/security/local-sasl-ssl/client.properties --topic orders.created --property parse.key=true --property key.separator=:
```

Send a record:

```text
1001:{"order_id":"1001","status":"CREATED"}
```

## Step 9: Test a Consumer

Example:

```bash
kafka-console-consumer --bootstrap-server localhost:9093 --consumer.config examples/security/local-sasl-ssl/client.properties --topic orders.created --group orders-created-demo --from-beginning
```

## What To Validate

- trusted clients connect successfully
- unauthorized clients fail
- ACLs deny operations not explicitly allowed
- topic access works only for the intended principal

## Common Local Failures

- truststore path is wrong
- certificate hostname does not match the advertised listener
- security protocol is mismatched between client and broker
- SASL mechanism differs on the two sides
- topic ACL exists but consumer group ACL is missing
- Schema Registry or Connect use different Kafka client security settings than your working CLI clients

## Practical Guidance

- separate admin and application credentials
- keep the listener name, security protocol, and trust configuration documented together
- test both success and denial cases
- keep related platform components on the same documented security model
- once the mental model is clear locally, move to your production-approved security pattern

## Next Step

Proceed to `kafka-security.md` if you want the broader design view, or to `schema-registry.md` if you want to extend secure patterns into governed schemas.