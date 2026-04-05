#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

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
	podman)
		compose_file="$REPO_ROOT/Install-scripts/podman/compose.yml"
		compose_cmd=(podman compose -f "$compose_file")
		;;
	docker)
		compose_file="$REPO_ROOT/Install-scripts/docker/docker-compose.yml"
		compose_cmd=(docker compose -f "$compose_file")
		;;
	*)
		echo "Unsupported CONTAINER_RUNTIME: $runtime"
		exit 1
		;;
esac

"${compose_cmd[@]}" up -d broker schema-registry connect ksqldb-server ksqldb-cli control-center

cat <<EOF
ksqlDB local stack started with ${runtime^}.

Endpoints:
- ksqlDB Server: http://localhost:8088
- Schema Registry: http://localhost:8081
- Kafka Connect: http://localhost:8083
- Control Center: http://localhost:9021
EOF