"""Describe the Kafka cluster in detail.

Shows where Kafka is installed, which ports each broker listens on,
security settings, log directories, Confluent Platform version, and
the reachable service endpoints — for both cloud and on-prem.

On-prem data sources
--------------------
- Broker metadata / configs : AdminClient (native SASL_SSL, ports 9094-9096)
- Platform version           : ksqlDB /info  (proxied at /ksqldb/info)
- Service endpoints          : HTTP checks against SR, Connect, ksqlDB, CMF

Usage
-----
    KAFKA_ENV=cloud  python3 scripts/kafka/describe_cluster.py
    KAFKA_ENV=onprem python3 scripts/kafka/describe_cluster.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from confluent_kafka import Consumer, KafkaException
from confluent_kafka.admin import AdminClient, ConfigResource

from auth import get_env, http_session, kafka_config

# Broker-level config keys that describe installation layout
_BROKER_KEYS = [
    "listeners",
    "advertised.listeners",
    "listener.security.protocol.map",
    "inter.broker.listener.name",
    "log.dirs",
    "log.dir",
    "zookeeper.connect",
    "num.partitions",
    "default.replication.factor",
    "min.insync.replicas",
]


# ── formatting helpers ─────────────────────────────────────────────────────────

def _section(title: str) -> None:
    width = 64
    print(f"\n{'─' * width}")
    print(f"  {title}")
    print(f"{'─' * width}")


def _kv(label: str, value: object) -> None:
    print(f"  {label:<40}{value}")


# ── shared: build AdminClient + pull metadata ──────────────────────────────────

def _get_metadata(cfg: dict):
    """Return (AdminClient, Consumer metadata) for the given kafka config."""
    admin = _admin_client(cfg)
    consumer = Consumer(cfg)
    try:
        meta = consumer.list_topics(timeout=15)
    except KafkaException as exc:
        sys.exit(f"Kafka error: {exc}")
    finally:
        consumer.close()
    return admin, meta


def _admin_client(cfg: dict) -> AdminClient:
    """Return an AdminClient with consumer-only keys stripped to avoid CONFWARN."""
    admin_cfg = {k: v for k, v in cfg.items()
                 if k not in ("group.id", "session.timeout.ms")}
    return AdminClient(admin_cfg)


def _broker_configs(admin: AdminClient, broker_ids: list[int]) -> dict[int, dict]:
    """Return {broker_id: {key: value}} for the keys in _BROKER_KEYS.

    describe_configs only accepts one BROKER ConfigResource per call,
    so we issue one request per broker sequentially.
    """
    result = {}
    for bid in broker_ids:
        resource = ConfigResource(ConfigResource.Type.BROKER, str(bid))
        futures = admin.describe_configs([resource])
        for _, future in futures.items():
            try:
                configs = future.result()
                result[bid] = {
                    k: configs[k].value
                    for k in _BROKER_KEYS
                    if k in configs and configs[k].value not in (None, "")
                }
            except Exception as exc:
                result[bid] = {"_error": str(exc)}
    return result


# ── cloud ──────────────────────────────────────────────────────────────────────

def _cloud_describe() -> None:
    cfg = kafka_config(client_id="describe-cluster-client",
                       group_id="describe-cluster-grp")
    admin, meta = _get_metadata(cfg)

    _section("Cloud — Cluster overview")
    _kv("Cluster ID",        meta.cluster_id or "n/a")
    _kv("Bootstrap servers", cfg["bootstrap.servers"])
    _kv("Security protocol", cfg["security.protocol"])
    _kv("SASL mechanism",    cfg["sasl.mechanisms"])
    _kv("Broker count",      len(meta.brokers))
    _kv("Topic count",       len(meta.topics))

    _section("Cloud — Broker endpoints")
    for bid, broker in sorted(meta.brokers.items()):
        _kv(f"Broker {bid}", f"{broker.host}:{broker.port}")

    configs = _broker_configs(admin, list(meta.brokers))

    _section("Cloud — Broker configuration (key settings)")
    for bid, cfg_map in sorted(configs.items()):
        print(f"\n  Broker {bid}:")
        if "_error" in cfg_map:
            print(f"    (config unavailable: {cfg_map['_error']})")
            continue
        for key, val in cfg_map.items():
            print(f"    {key:<40}{val}")


# ── on-prem ────────────────────────────────────────────────────────────────────

def _onprem_describe() -> None:
    # ── 1. Native Kafka metadata + broker configs ──────────────────────────────
    cfg = kafka_config(client_id="describe-cluster-client",
                       group_id="describe-cluster-grp")
    admin, meta = _get_metadata(cfg)
    broker_cfgs = _broker_configs(admin, list(meta.brokers))

    _section("On-prem — Cluster overview")
    _kv("Cluster ID",           meta.cluster_id or "n/a")
    _kv("VM host (floating IP)", os.getenv("VM_FLOATING_IP", "unknown"))
    _kv("Bootstrap servers",    os.getenv("VM_BOOTSTRAP_SERVERS", "unknown"))
    _kv("Security protocol",    os.getenv("VM_SECURITY_PROTOCOL", "SASL_SSL"))
    _kv("SASL mechanism",       os.getenv("VM_SASL_MECHANISMS", "PLAIN"))
    _kv("SASL username",        os.getenv("VM_SASL_USERNAME", "unknown"))
    _kv("CA cert path",         os.getenv("VM_KAFKA_CA_CERT", "./kafka-ca.crt"))
    _kv("Broker count",         len(meta.brokers))
    _kv("Topic count",          len(meta.topics))

    # ── 2. Per-broker listener / install detail ────────────────────────────────
    _section("On-prem — Broker listeners / install layout")
    for bid, broker in sorted(meta.brokers.items()):
        print(f"\n  Broker {bid}  ({broker.host}:{broker.port})")
        cfg_map = broker_cfgs.get(bid, {})
        if "_error" in cfg_map:
            print(f"    (config unavailable: {cfg_map['_error']})")
            continue
        display_keys = [
            "listeners",
            "advertised.listeners",
            "listener.security.protocol.map",
            "inter.broker.listener.name",
            "log.dirs",
            "log.dir",
            "num.partitions",
            "default.replication.factor",
            "min.insync.replicas",
            "zookeeper.connect",
        ]
        for key in display_keys:
            if key in cfg_map:
                print(f"    {key:<40}{cfg_map[key]}")

    # ── 3. Platform version via ksqlDB /info ───────────────────────────────────
    _section("On-prem — Platform version")
    try:
        session, base = http_session("KSQLDB_URL")
        r = session.get(f"{base}/info", timeout=10)
        if r.status_code == 200 and "json" in r.headers.get("Content-Type", ""):
            info = r.json().get("KsqlServerInfo", {})
            _kv("ksqlDB version",    info.get("version", "n/a"))
            _kv("Kafka cluster ID",  info.get("kafkaClusterId", "n/a"))
            _kv("ksqlDB status",     info.get("serverStatus", "n/a"))
        else:
            _kv("ksqlDB version",    f"(HTTP {r.status_code})")
    except Exception as exc:
        _kv("ksqlDB version",        f"(unreachable: {exc})")

    # Install path is well-known for Confluent Platform packages
    install_path = "/opt/confluent"
    _kv("Confluent install path",    install_path)
    _kv("Kafka CA cert (on VM)",     "/var/lib/confluent/kafka-ca.crt")

    # ── 4. Service endpoints ───────────────────────────────────────────────────
    _section("On-prem — Service endpoints")
    services = {
        "Control Center":  ("CONTROL_CENTER_URL",  "/"),
        "Schema Registry": ("SCHEMA_REGISTRY_URL", "/subjects"),
        "ksqlDB":          ("KSQLDB_URL",          "/info"),
        "Kafka Connect":   ("KAFKA_CONNECT_URL",   "/connectors"),
        "CMF REST":        ("CMF_REST_URL",         "/api/v1/environments"),
    }
    try:
        chk_session, _ = http_session("CONTROL_CENTER_URL")
    except Exception:
        chk_session = None

    for name, (env_key, probe_path) in services.items():
        url = os.getenv(env_key, "n/a").rstrip("/")
        status = ""
        if chk_session and url != "n/a":
            try:
                r = chk_session.get(f"{url}{probe_path}", timeout=8)
                status = f"  ✓ HTTP {r.status_code}"
            except Exception as exc:
                status = f"  ✗ {exc}"
        _kv(f"  {name}", f"{url}{status}")

    # ── 5. Kafka broker port summary ───────────────────────────────────────────
    _section("On-prem — Kafka broker port summary")
    bootstrap = os.getenv("VM_BOOTSTRAP_SERVERS", "")
    entries = [s.strip() for s in bootstrap.split(",") if s.strip()]
    for entry in entries:
        host, _, port = entry.rpartition(":")
        _kv(f"  {host}", f"port {port}  (SASL_SSL / PLAIN)")


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    env = get_env()
    print(f"Kafka cluster description  [{env}]")
    if env == "cloud":
        _cloud_describe()
    else:
        _onprem_describe()
