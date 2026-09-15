"""
CFK & Confluent on OpenShift/Kubernetes MCP Server
Provides real-time inspection and management tools for Confluent Platform on Kubernetes.
"""

import json
import os
import subprocess
from typing import Any, Dict, List, Optional
from mcp.server.mcpserver import MCPServer as FastMCP

mcp = FastMCP("cfk-openshift")

NAMESPACE = os.environ.get("CONFLUENT_NAMESPACE", "confluent")


def run_oc(cmd: List[str]) -> str:
    """Helper to run oc commands safely."""
    try:
        full_cmd = ["oc"] + cmd
        res = subprocess.run(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        if res.returncode != 0:
            return f"Error ({res.returncode}): {res.stderr.strip() or res.stdout.strip()}"
        return res.stdout.strip()
    except Exception as e:
        return f"Execution error: {str(e)}"


@mcp.tool()
def get_cluster_health(namespace: str = NAMESPACE) -> str:
    """Get the overall health of all pods, statefulsets, and deployments in the Confluent namespace."""
    pods_out = run_oc(["get", "pods", "-n", namespace, "-o", "wide"])
    return f"=== Pods in {namespace} ===\n{pods_out}"


@mcp.tool()
def get_cfk_resources(namespace: str = NAMESPACE) -> str:
    """List all Confluent Platform Custom Resources (Kafka, KRaft, Connect, Schema Registry, ksqlDB, Control Center, Connectors)."""
    crs = [
        "kraftcontroller",
        "kafka",
        "schemaregistry",
        "connect",
        "connector",
        "ksqldb",
        "controlcenter",
        "kafkarestproxy",
    ]
    results = []
    for cr in crs:
        out = run_oc(["get", cr, "-n", namespace, "--no-headers"])
        if out and not out.startswith("Error") and not out.startswith("No resources"):
            results.append(f"[{cr.upper()}]\n{out}")
    return "\n\n".join(results) if results else "No Confluent custom resources found."


@mcp.tool()
def list_connectors(namespace: str = NAMESPACE) -> str:
    """List all deployed Kafka Connect connectors and their running tasks/states."""
    return run_oc(["get", "connectors", "-n", namespace])


@mcp.tool()
def get_connector_status(connector_name: str, cluster_name: str = "connect-pg", namespace: str = NAMESPACE) -> str:
    """Query the Kafka Connect REST API on a worker pod to get detailed connector & task status."""
    pod_name = f"{cluster_name}-0"
    cmd = [
        "exec",
        pod_name,
        "-n",
        namespace,
        "-c",
        cluster_name,
        "--",
        "curl",
        "-s",
        f"http://localhost:8083/connectors/{connector_name}/status",
    ]
    raw = run_oc(cmd)
    try:
        parsed = json.loads(raw)
        return json.dumps(parsed, indent=2)
    except Exception:
        return raw


@mcp.tool()
def list_kafka_topics(namespace: str = NAMESPACE) -> str:
    """List all Kafka topics in the cluster via kafka-topics inside kafka-0."""
    cmd = [
        "exec",
        "kafka-0",
        "-n",
        namespace,
        "-c",
        "kafka",
        "--",
        "kafka-topics",
        "--bootstrap-server",
        "kafka:9071",
        "--list",
    ]
    return run_oc(cmd)


@mcp.tool()
def read_kafka_topic(topic: str, max_messages: int = 5, namespace: str = NAMESPACE) -> str:
    """Read the latest messages from a Kafka topic using kafka-console-consumer."""
    cmd = [
        "exec",
        "kafka-0",
        "-n",
        namespace,
        "-c",
        "kafka",
        "--",
        "kafka-console-consumer",
        "--bootstrap-server",
        "kafka:9071",
        "--topic",
        topic,
        "--from-beginning",
        "--max-messages",
        str(max_messages),
        "--timeout-ms",
        "10000",
    ]
    return run_oc(cmd)


@mcp.tool()
def list_schema_subjects(namespace: str = NAMESPACE) -> str:
    """List all registered Avro/JSON schema subjects in Confluent Schema Registry."""
    cmd = [
        "exec",
        "schemaregistry-0",
        "-n",
        namespace,
        "-c",
        "schemaregistry",
        "--",
        "curl",
        "-s",
        "http://localhost:8081/subjects",
    ]
    return run_oc(cmd)


@mcp.tool()
def get_cluster_routes(namespace: str = NAMESPACE) -> str:
    """List all active OpenShift Routes for Control Center, Flink, MinIO, etc."""
    return run_oc(["get", "routes", "-n", namespace])


if __name__ == "__main__":
    mcp.run(transport="stdio")
