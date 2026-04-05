#!/usr/bin/env bash
set -euo pipefail

docker exec -it ksqldb-cli ksql http://ksqldb-server:8088