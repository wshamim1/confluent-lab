#!/usr/bin/env bash
set -euo pipefail

for command in kubectl oc; do
  if command -v "$command" >/dev/null 2>&1; then
    echo "$command: found"
  else
    echo "$command: not found"
  fi
done

echo
echo "Verify manually before installing Confluent on Kubernetes or OpenShift:"
echo "- storage classes for stateful workloads"
echo "- ingress or route strategy"
echo "- TLS and secret management"
echo "- supported Confluent deployment method for your cluster"