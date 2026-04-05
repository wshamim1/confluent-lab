#!/usr/bin/env bash
set -euo pipefail

curl --silent http://localhost:8081/subjects | tr ',' '\n'