#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runtime="${CONTAINER_RUNTIME:-}"

if [[ -z "$runtime" ]]; then
	if command -v podman >/dev/null 2>&1; then
		runtime="podman"
	elif command -v docker >/dev/null 2>&1; then
		runtime="docker"
	else
		echo "Neither podman nor docker is installed"
		exit 1
	fi
fi

case "$runtime" in
	podman|docker)
		"$runtime" exec -i ksqldb-cli ksql http://ksqldb-server:8088 < "$SCRIPT_DIR/ksql-demo.sql"
		;;
	*)
		echo "Unsupported CONTAINER_RUNTIME: $runtime"
		exit 1
		;;
esac