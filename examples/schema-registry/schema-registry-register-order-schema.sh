#!/usr/bin/env bash
set -euo pipefail

curl --silent --show-error \
  -X POST http://localhost:8081/subjects/orders.created-value/versions \
  -H 'Content-Type: application/vnd.schemaregistry.v1+json' \
  -d '{
    "schema": "{\"type\":\"record\",\"name\":\"OrderCreated\",\"fields\":[{\"name\":\"order_id\",\"type\":\"string\"},{\"name\":\"customer_id\",\"type\":\"string\"},{\"name\":\"total_amount\",\"type\":\"double\"},{\"name\":\"currency\",\"type\":\"string\",\"default\":\"USD\"}]}"
  }'

echo