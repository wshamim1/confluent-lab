# Troubleshooting: Flink + Schema Registry Auth & Avro Wire Format

> **Environment:** On-prem Confluent Platform (IBM Cloud VSI)  
> **Components:** CMF / Apache Flink, Schema Registry, Kafka, Python producer  
> **Symptoms fixed:** `Cannot retrieve table flink-database.<topic>` and `SELECT *` stuck in `PENDING` / `RESTARTING`

---

## Overview

Two independent misconfigurations were present from initial cluster provisioning.
Both were silent — no startup errors — but they caused every Flink SQL table query
to fail at runtime.

```
cluster provisioned
       │
       ├─ flink-catalog.json deployed → SR URL ✓, SR credentials ✗
       │         └─ SHOW TABLES → "Cannot retrieve table"          [Problem 1]
       │
       └─ producer.py started → messages written as plain JSON
                 └─ SELECT * → "Unknown magic byte!" → RESTARTING  [Problem 2]
                                    (surfaces as PENDING in the CLI)
```

---

## Problem 1 — Flink KafkaCatalog auth error against Schema Registry

### Symptom

```
> select * from `retail-orders`;
Error: statement phase is: FAILED
Error details: SQL validation failed. Cannot retrieve table flink-database.retail-orders
```

### Root cause

`/opt/confluent-installer/scripts/flink-catalog.json` on the VM was missing
Basic Auth credentials for Schema Registry.  The Schema Registry CRD has
`authentication.type: basic` enforced, so every unauthenticated request returns
`401 Unauthorized`.  Flink swallowed the 401 and reported it as a table-not-found
validation failure.

**File:** `/opt/confluent-installer/scripts/flink-catalog.json`

```json
// BEFORE — missing auth
{
  "apiVersion": "cmf.confluent.io/v1",
  "kind": "KafkaCatalog",
  "metadata": { "name": "flink-catalog" },
  "spec": {
    "srInstance": {
      "connectionConfig": {
        "schema.registry.url": "http://schemaregistry.confluent.svc.cluster.local:8081"
      }
    }
  }
}
```

```json
// AFTER — with auth
{
  "apiVersion": "cmf.confluent.io/v1",
  "kind": "KafkaCatalog",
  "metadata": { "name": "flink-catalog" },
  "spec": {
    "srInstance": {
      "connectionConfig": {
        "schema.registry.url": "http://schemaregistry.confluent.svc.cluster.local:8081",
        "basic.auth.credentials.source": "USER_INFO",
        "basic.auth.user.info": "admin:<CONTROL_CENTER_PASSWORD>"
      }
    }
  }
}
```

### Fix (applied live)

```bash
# 1. Update the file on the VM
scp -i cflt-vsi-key.pem flink-catalog-patch.json root@<VM_IP>:/tmp/flink-catalog-patch.json

# 2. Apply via the confluent CLI (talks directly to CMF NodePort, no nginx auth needed)
ssh -i cflt-vsi-key.pem root@<VM_IP> '
  CMF_URL="http://$(minikube ip):30022"
  confluent flink catalog update /tmp/flink-catalog-patch.json --url "$CMF_URL"
'

# 3. Update the installer file so re-deployments don't regress
ssh -i cflt-vsi-key.pem root@<VM_IP> \
  'cp /tmp/flink-catalog-patch.json /opt/confluent-installer/scripts/flink-catalog.json'
```

### Verify fix

```bash
# SHOW TABLES must now list all schema-backed topics
confluent flink shell \
  --url https://admin:<password>@<VM_IP> \
  --environment flink-env \
  --compute-pool flink-compute-pool \
  --catalog flink-catalog \
  --database flink-database
> SHOW TABLES;
# Expected: retail-orders, retail-returns, retail-browse, sensor-readings, …
```

---

## Problem 2 — SELECT stuck in PENDING / RESTARTING (Unknown magic byte)

### Symptom

```
> select * from `retail-orders`;
Waiting for statement to be ready. Statement phase is PENDING. (Timeout 6s/600s)
Waiting for statement to be ready. Statement phase is PENDING. (Timeout 12s/600s)
…
```

The Flink job shows `RESTARTING` in the jobs overview. Flink REST `/jobs/<jid>/exceptions` reveals:

```
java.lang.IllegalArgumentException: Unknown magic byte!
  at SchemaId.fromBytes(SchemaId.java:70)
Caused by: io.confluent.flink.util.InvalidSchemaRegistryInputException:
           Failed to deserialize Avro record.
```

### Root cause

`usecases/retail/producer.py` was serialising messages as **plain JSON**, not as
**Confluent Avro wire format**.  Flink's KafkaCatalog expects every message to
begin with:

```
0x00  (magic byte)
[4 bytes: schema ID as big-endian int]
[Avro binary payload]
```

A JSON string starts with `0x7b` (`{`), which is not a recognised magic byte.
The task failed immediately on the first consumed message, Flink restarted it,
it failed again — this loop appeared as indefinite `PENDING` in the CLI.

**File:** `usecases/retail/producer.py`

```python
# BEFORE — plain JSON, no wire format
p.produce(
    topic,
    key=customer["customer_id"],
    value=json.dumps(evt).encode(),   # 0x7b 0x22 ... — wrong
    callback=_delivery_report,
)
```

```python
# AFTER — Avro with Confluent wire format (0x00 + schema_id + avro)
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import SerializationContext, MessageField

avro_bytes = serializers[topic](
    evt, SerializationContext(topic, MessageField.VALUE)
)
p.produce(
    topic,
    key=customer["customer_id"],
    value=avro_bytes,                 # 0x00 0x00 0x00 0x00 0x12 ... — correct
    callback=_delivery_report,
)
```

### Fix (applied to codebase)

The full `AvroSerializer` wiring is in `usecases/retail/producer.py`.
After editing the producer the existing (bad) messages must be purged:

```bash
# 1. Delete and recreate the three retail topics to flush JSON messages
ssh -i cflt-vsi-key.pem root@<VM_IP> '
  for topic in retail-orders retail-returns retail-browse; do
    kubectl exec -n confluent kafka-0 -- kafka-topics \
      --bootstrap-server localhost:9071 --delete --topic $topic
  done
  sleep 3
  for topic in retail-orders retail-returns retail-browse; do
    kubectl exec -n confluent kafka-0 -- kafka-topics \
      --bootstrap-server localhost:9071 --create --topic $topic \
      --partitions 6 --replication-factor 3
  done
'

# 2. Re-seed the topics with properly encoded Avro messages
KAFKA_ENV=onprem .venv/bin/python usecases/retail/producer.py --burst 50
```

### Verify fix

```bash
# First 5 bytes of a message must be: 00 00 00 00 <schema_id>
ssh -i cflt-vsi-key.pem root@<VM_IP> '
  kubectl exec -n confluent kafka-0 -- bash -c "
    kafka-console-consumer \
      --bootstrap-server localhost:9071 \
      --topic retail-orders \
      --from-beginning --max-messages 1 2>/dev/null | od -A x -t x1z | head -1
  "
'
# Expected first bytes: 00 00 00 00 12   (magic=0x00, schema_id=18)
```

Then in the Flink shell:

```sql
> SELECT event_id, customer_id, product_name, total, status
  FROM `retail-orders` LIMIT 5;
-- Should stream rows within a few seconds
```

---

## Quick Diagnostic Reference

| Symptom | Check | Likely cause |
|---|---|---|
| `Cannot retrieve table flink-database.<topic>` | `curl -sk -u admin:<pass> https://<VM>/sr/subjects` | SR 401 — catalog missing auth credentials |
| `SELECT` stays `PENDING` then `RESTARTING` | `kubectl port-forward … 8081:8081` → `/jobs/<jid>/exceptions` | `Unknown magic byte` — producer wrote JSON not Avro |
| `SHOW TABLES` empty | `curl … /sr/subjects` | No schemas registered — run `register_all_schemas.py` |
| `SHOW TABLES` lists topic but `SELECT` fails compile | Schema field mismatch | Schema in SR doesn't match Avro schema in producer |

### Useful one-liners

```bash
# Check SR connectivity and subjects
curl -sk -u admin:<pass> https://<VM>/sr/subjects | python3 -m json.tool

# Check SR auth from inside the cluster
kubectl exec -n confluent schemaregistry-0 -- \
  curl -s -u admin:<pass> http://localhost:8081/subjects

# Inspect raw bytes of a Kafka message (magic byte check)
kubectl exec -n confluent kafka-0 -- bash -c "
  kafka-console-consumer --bootstrap-server localhost:9071 \
    --topic <topic> --from-beginning --max-messages 1 2>/dev/null \
  | od -A x -t x1z | head -2"
# Avro wire format:  00 00 00 00 XX ...
# Plain JSON:        7b 22 ...         ← wrong

# Check Flink job exceptions via REST
kubectl port-forward -n confluent svc/flink-compute-pool-rest 8081:8081 &
curl -s http://localhost:8081/jobs/overview   # find the failing JID
curl -s http://localhost:8081/jobs/<JID>/exceptions | python3 -m json.tool

# Re-register all schemas (idempotent, safe to re-run)
KAFKA_ENV=onprem python3 scripts/platform/register_all_schemas.py

# Re-seed all retail topics with Avro messages
KAFKA_ENV=onprem .venv/bin/python usecases/retail/producer.py --burst 50
```

---

## Files Changed

| File | Change |
|---|---|
| `/opt/confluent-installer/scripts/flink-catalog.json` (VM) | Added `basic.auth.credentials.source` and `basic.auth.user.info` to `srInstance.connectionConfig` |
| `usecases/retail/producer.py` | Replaced `json.dumps().encode()` with `AvroSerializer` + Confluent wire format |
