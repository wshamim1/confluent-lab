#!/usr/bin/env bash
set -euo pipefail

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
		"$runtime" exec -it ksqldb-cli ksql http://ksqldb-server:8088
		;;
	*)
		echo "Unsupported CONTAINER_RUNTIME: $runtime"
		exit 1
		;;
esac