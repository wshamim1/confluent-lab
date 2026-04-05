#!/usr/bin/env bash
set -euo pipefail

podman exec -it ksqldb-cli ksql http://ksqldb-server:8088