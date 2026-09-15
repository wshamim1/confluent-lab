"""
auth.py — Centralised authentication for Confluent Cloud and on-prem VM.

Usage
-----
Set KAFKA_ENV in your .env (or shell) to select the target environment:

    KAFKA_ENV=cloud    → Confluent Cloud (SASL_SSL + API key/secret)
    KAFKA_ENV=onprem   → On-prem VM via Control Center REST API

Then import and call the helper you need:

    from auth import kafka_config, http_session, get_env

    # Kafka producer / consumer config dict
    cfg = kafka_config(client_id="my-client", group_id="my-group")

    # requests.Session pre-configured for Control Center (onprem only)
    session, base_url = http_session()

    # Active environment name: "cloud" or "onprem"
    env = get_env()
"""

import os
import sys

import requests
import urllib3
from dotenv import load_dotenv

load_dotenv()

# ── Environment selection ──────────────────────────────────────────────────────
_VALID_ENVS = ("cloud", "onprem")


def get_env() -> str:
    """Return the active environment: 'cloud' or 'onprem'.

    Reads KAFKA_ENV from .env / shell.  Defaults to 'cloud'.
    """
    env = os.getenv("KAFKA_ENV", "cloud").lower().strip()
    if env not in _VALID_ENVS:
        sys.exit(
            f"KAFKA_ENV='{env}' is invalid. "
            f"Choose one of: {', '.join(_VALID_ENVS)}"
        )
    return env


# ── Cloud auth ─────────────────────────────────────────────────────────────────

def _cloud_config(client_id: str, group_id: str | None) -> dict:
    """Build a confluent-kafka config dict for Confluent Cloud."""
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    api_key    = os.getenv("CONFLUENT_CLOUD_API_KEY")
    api_secret = os.getenv("CONFLUENT_CLOUD_API_SECRET")

    missing = [
        name for name, val in {
            "KAFKA_BOOTSTRAP_SERVERS":  bootstrap,
            "CONFLUENT_CLOUD_API_KEY":  api_key,
            "CONFLUENT_CLOUD_API_SECRET": api_secret,
        }.items() if not val
    ]
    if missing:
        sys.exit(f"[cloud] Missing .env settings: {', '.join(missing)}")

    cfg = {
        "bootstrap.servers":  bootstrap,
        "security.protocol":  os.getenv("KAFKA_SECURITY_PROTOCOL", "SASL_SSL"),
        "sasl.mechanisms":    os.getenv("KAFKA_SASL_MECHANISMS", "PLAIN"),
        "sasl.username":      api_key,
        "sasl.password":      api_secret,
        "session.timeout.ms": int(os.getenv("KAFKA_SESSION_TIMEOUT_MS", "45000")),
        "client.id":          client_id,
    }
    if group_id:
        cfg["group.id"] = group_id
    return cfg


# ── On-prem auth ───────────────────────────────────────────────────────────────

def _onprem_config(client_id: str, group_id: str | None) -> dict:
    """Build a confluent-kafka config dict for the on-prem VM broker.

    Brokers listen on ports 9094/9095/9096 with SASL_SSL + PLAIN.
    Requires VM_BOOTSTRAP_SERVERS, VM_SASL_USERNAME, VM_SASL_PASSWORD,
    and VM_KAFKA_CA_CERT (path to the CA cert downloaded from the VM).
    """
    bootstrap = os.getenv("VM_BOOTSTRAP_SERVERS")
    if not bootstrap:
        sys.exit("[onprem] Missing VM_BOOTSTRAP_SERVERS in .env")

    vm_user = os.getenv("VM_SASL_USERNAME")
    vm_pass = os.getenv("VM_SASL_PASSWORD")
    ca_cert = os.getenv("VM_KAFKA_CA_CERT", "./kafka-ca.crt")

    missing = [n for n, v in {
        "VM_SASL_USERNAME": vm_user,
        "VM_SASL_PASSWORD": vm_pass,
    }.items() if not v]
    if missing:
        sys.exit(f"[onprem] Missing .env settings: {', '.join(missing)}")

    cfg = {
        "bootstrap.servers":        bootstrap,
        "security.protocol":        os.getenv("VM_SECURITY_PROTOCOL", "SASL_SSL"),
        "sasl.mechanisms":          os.getenv("VM_SASL_MECHANISMS", "PLAIN"),
        "sasl.username":            vm_user,
        "sasl.password":            vm_pass,
        "ssl.ca.location":          ca_cert,
        "ssl.endpoint.identification.algorithm": "https",
        "session.timeout.ms":       int(os.getenv("KAFKA_SESSION_TIMEOUT_MS", "45000")),
        "client.id":                client_id,
    }
    if group_id:
        cfg["group.id"] = group_id
    return cfg


def http_session(base_url_env: str = "CONTROL_CENTER_URL") -> tuple[requests.Session, str]:
    """Return a (session, base_url) tuple for an HTTPS endpoint on the VM.

    Only valid when KAFKA_ENV=onprem.  Pass ``base_url_env`` to target a
    different component URL variable (e.g. ``"KSQLDB_URL"``).
    Skips TLS verification for the VM's self-signed certificate and follows
    HTTP→HTTPS redirects automatically.
    """
    if get_env() != "onprem":
        sys.exit("http_session() is only available when KAFKA_ENV=onprem")

    base_url = os.getenv(base_url_env, "").rstrip("/")
    cc_user  = os.getenv("CONTROL_CENTER_USERNAME", "admin")
    cc_pass  = os.getenv("CONTROL_CENTER_PASSWORD", "")

    if not base_url or not cc_pass:
        sys.exit(
            f"[onprem] Missing {base_url_env} or CONTROL_CENTER_PASSWORD in .env"
        )

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()
    session.auth          = (cc_user, cc_pass)
    session.verify        = False
    session.max_redirects = 5
    return session, base_url


# ── Public API ─────────────────────────────────────────────────────────────────

def kafka_config(
    client_id: str = "confluent-client",
    group_id:  str | None = None,
) -> dict:
    """Return a confluent-kafka config dict for the active KAFKA_ENV.

    Parameters
    ----------
    client_id : str
        Value for the ``client.id`` Kafka property.
    group_id : str | None
        Value for the ``group.id`` Kafka property (omitted when None).
    """
    env = get_env()
    if env == "cloud":
        return _cloud_config(client_id, group_id)
    return _onprem_config(client_id, group_id)
