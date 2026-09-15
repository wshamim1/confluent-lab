# confluent-lab

A hands-on Python + Streamlit lab for working with both **Confluent Cloud** and an **on-prem Confluent Platform VM**. Includes utility scripts to inspect clusters, manage topics, produce/consume messages, and run ksqlDB queries — plus two full **streaming use-case demos** with live dashboards and MCP agent chat.

---

## Table of Contents

1. [Use Cases](#use-cases)
   - [Predictive Maintenance](#-predictive-maintenance)
   - [Real-Time Transit](#-real-time-transit)
2. [Project Layout](#project-layout)
3. [Prerequisites](#prerequisites)
4. [Setup](#setup)
5. [Environment Switching](#environment-switching)
6. [auth.py — shared authentication](#authpy--shared-authentication-module)
7. [Utility Scripts](#utility-scripts)
8. [Flink SQL Shell](#flink-sql-shell)
9. [On-Prem Platform Quick Reference](#on-prem-platform-quick-reference)
10. [CFK External-Access Lab](#scriptscfk-external-access--level-4-lab-automation)
11. [Tutorials](#tutorials)
12. [Dependencies](#dependencies)

---

## Use Cases

Both use cases live under `usecases/` and share the root `auth.py` for Kafka connectivity. Each has its own producer, Streamlit multi-page dashboard, and MCP server.

### 🔧 Predictive Maintenance

> **On-prem Confluent Platform · Flink SQL anomaly detection · Linear work orders · MCP agent chat**

```
sensor_producer.py
4 machines × 3 sensors  ──►  sensor-readings (Kafka)
                                     │
                              Flink SQL (ksqlDB)
                         tumbling 1-min window anomaly
                                     │
                          equipment-alerts (Kafka)
                         ┌───────────┴───────────┐
                         ▼                       ▼
               maintenance_agent.py      Streamlit dashboard
               (streaming consumer)      dashboard/app.py
                         │               • sensor charts
                         ▼               • alert table
                 MCP Server (13 tools)   • agent activity log
                 • kafka_read_alerts     • inject-anomaly button
                 • get_part_history      • pipeline diagram
                 • create_work_order     pages/flink_analytics.py
                 • get_machine_status    pages/chat.py (MCP chat)
                         │
                         ▼
                  Linear work order
                  (technician notified)
```

#### Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the sensor producer
KAFKA_ENV=onprem python3 usecases/predictive_maintenance/scripts/sensor_producer.py

# 3. Deploy Flink SQL anomaly detection (ksqlDB)
KAFKA_ENV=onprem python3 usecases/predictive_maintenance/scripts/flink_anomaly_setup.py --deploy

# 4. Launch the dashboard  (port 8501)
bash usecases/predictive_maintenance/run.sh

# 5. (Optional) Run the streaming agent
KAFKA_ENV=onprem python3 usecases/predictive_maintenance/agent/maintenance_agent.py
```

#### Inject a test anomaly

```bash
# Via the MCP tool in Bob chat, or directly:
KAFKA_ENV=onprem python3 usecases/predictive_maintenance/scripts/sensor_producer.py \
    --inject-anomaly --machine-id turbine-1 --sensor-type vibration --count 30
```

#### Topics used

| Topic | Producer | Consumer |
|---|---|---|
| `sensor-readings` | `sensor_producer.py` | Flink SQL, dashboard |
| `equipment-alerts` | Flink SQL anomaly job | dashboard, agent, MCP server |
| `agent-activity` | `maintenance_agent.py` | dashboard work-order log |

---

### 🚆 Real-Time Transit

> **On-prem Confluent Platform · live departure board · delay injection · MCP agent chat**

```
producer.py
12 routes (flights/trains/buses) ──►  transit-schedules  (Kafka, seed)
                                  ──►  transit-events     (Kafka, live)
                                               │
                                    Streamlit dashboard
                                    dashboard/app.py
                                    • live departure board
                                    • KPI strip (on-time %, avg delay)
                                    • inject delay (sidebar)
                                    • pipeline architecture diagram
                                    pages/analytics.py  (Flink SQL charts)
                                    pages/chat.py       (MCP agent chat)
                                               │
                                    MCP Server (6 tools)
                                    • transit_read_events
                                    • transit_get_route_status
                                    • transit_get_delayed_trips
                                    • transit_get_carrier_stats
                                    • transit_inject_delay
                                    • transit_get_trip_detail
```

#### Quick start

```bash
# 1. Seed the schedule and start producing live events
KAFKA_ENV=onprem python3 usecases/transit/producer.py

# 2. Launch the dashboard  (port 8502)
bash usecases/transit/run.sh
```

#### Topics used

| Topic | Content | Offset reset |
|---|---|---|
| `transit-schedules` | Planned schedule seed (trip_id, route, carrier, departure) | `earliest` |
| `transit-events` | Live status updates (on_time / delayed / cancelled, delay_minutes) | `earliest` |

#### Inject a delay wave

Use the **Inject Delay** button in the dashboard sidebar, or ask the MCP agent:
> *"Inject a 30-minute delay on route AA-101"*

---

## Project Layout

```
confluent-lab/
│
├── auth.py                         # Shared auth — KAFKA_ENV → correct config dict
├── requirements.txt                # All Python dependencies
├── kafka-ca.crt                    # CA cert for on-prem broker TLS (not committed)
├── .env                            # Credentials and config (not committed)
│
├── usecases/
│   ├── predictive_maintenance/
│   │   ├── run.sh                              # Launch dashboard on port 8501
│   │   ├── scripts/
│   │   │   ├── sensor_producer.py              # Simulated IoT sensor readings
│   │   │   └── flink_anomaly_setup.py          # Deploy / manage ksqlDB anomaly detection
│   │   ├── dashboard/
│   │   │   ├── app.py                          # Main dashboard (charts, alerts, scheduler)
│   │   │   └── pages/
│   │   │       ├── flink_analytics.py          # 4-chart Flink SQL analytics + query log
│   │   │       └── chat.py                     # MCP agent chat (13 tools)
│   │   ├── mcp_server/
│   │   │   └── server.py                       # MCP server — 13 tools
│   │   ├── agent/
│   │   │   ├── maintenance_agent.py            # Streaming agent: alerts → work orders
│   │   │   └── webhook_receiver.py             # HTTP webhook receiver (HTTP Sink → agent)
│   │
│   └── transit/
│       ├── run.sh                              # Launch dashboard on port 8502
│       ├── producer.py                         # 12-route event simulator (flights/trains/buses)
│       ├── topics.py                           # Topic constants and status palettes
│       ├── dashboard/
│       │   ├── app.py                          # Departure board, KPI strip, scheduler
│       │   └── pages/
│       │       ├── analytics.py                # Delay analytics + Flink SQL + query log
│       │       └── chat.py                     # Transit MCP agent chat (6 tools)
│       └── mcp_server/
│           └── server.py                       # MCP server — 6 transit tools
│
├── scripts/
│   ├── kafka/
│   │   ├── list_topics.py          # List topics (cloud or on-prem)
│   │   ├── manage_topics.py        # Create, delete, describe, and list Kafka topics
│   │   ├── cluster_details.py      # Broker/topic metadata
│   │   ├── describe_cluster.py     # Full cluster description: ports, listeners, version
│   │   ├── consumer.py             # Consume messages (--from-beginning, --limit, --format)
│   │   ├── consumer_groups.py      # List groups, show lag, reset offsets
│   │   └── topic_tail.py           # Live tail of one or more topics
│   │
│   ├── producers/
│   │   ├── produce.py              # Produce to any topic (JSON, file, stdin, --repeat)
│   │   ├── publish_booking.py      # Publish a booking event to the "bookings" topic
│   │   └── mysql_to_kafka.py       # Local MySQL table → Kafka topic
│   │
│   ├── platform/
│   │   ├── explore.py              # Interactive REST explorer (SR, ksqlDB, Connect, CMF)
│   │   ├── health_check.py         # Ping every component — UP/DOWN/latency
│   │   ├── ksql_query.py           # Run ksqlDB statements from the CLI
│   │   └── register_schema.py      # Register an AVRO schema in Schema Registry
│   │
│   ├── connectors/
│   │   └── manage_connectors.py    # List, pause, resume, restart, delete connectors
│   │
│   ├── mysql/
│   │   └── start-mysql.sh          # MySQL 8 Podman container for local dev
│   │
│   ├── datagen/
│   │   └── setup-datagen.sh        # Deploy / stop datagen connectors on the VM
│   │
│   └── cfk-external-access/        # Level 4 lab: external client access automation
│       ├── run_lab.sh
│       ├── cleanup.sh
│       └── lib/                    # ex1_explore.sh … ex8_control_center.sh
│
├── .bob/
│   └── mcp.json                    # Bob MCP server registrations
│
├── ccloud-python-client/           # Standalone produce/consume example
│   ├── client.py
│   ├── client.properties           # create locally (not committed)
│   └── requirements.txt
│
├── cli/
│   ├── install.sh                  # Download the Confluent CLI (macOS)
│   └── list_topics.sh
│
└── bin/                            # Confluent CLI binary installed by cli/install.sh
```

---

## Prerequisites

- Python 3.11 or later
- A [Confluent Cloud](https://confluent.cloud) account **and/or** access to the on-prem VM (at `<YOUR_VM_IP>`)
- SSH key `cflt-vsi-key.pem` in the project root (for on-prem access)

---

## Setup

### 1. Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure `.env`

Copy the template below and fill in your values.
`KAFKA_ENV` controls which target all scripts use — set it once and all scripts follow.

```dotenv
# ── Environment selector: cloud | onprem ──────────────────────────────────────
KAFKA_ENV=onprem

# ── Confluent Cloud ───────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP_SERVERS=<your-bootstrap-server>:9092
CONFLUENT_CLOUD_API_KEY=<your-api-key>
CONFLUENT_CLOUD_API_SECRET=<your-api-secret>
KAFKA_SECURITY_PROTOCOL=SASL_SSL
KAFKA_SASL_MECHANISMS=PLAIN
KAFKA_SESSION_TIMEOUT_MS=45000
KAFKA_CLIENT_ID=confluent-lab-client

# ── On-prem VM ────────────────────────────────────────────────────────────────
VM_FLOATING_IP=<YOUR_VM_IP>
VM_SSH_KEY=cflt-vsi-key.pem
VM_SSH_USER=root
VM_BOOTSTRAP_SERVERS=<YOUR_VM_IP>:9094,<YOUR_VM_IP>:9095,<YOUR_VM_IP>:9096
VM_SECURITY_PROTOCOL=SASL_SSL
VM_SASL_MECHANISMS=PLAIN
VM_SASL_USERNAME=kafka-admin
VM_SASL_PASSWORD=<password>
VM_KAFKA_CA_CERT=./kafka-ca.crt

# ── On-prem: HTTPS endpoints (all use admin credentials) ─────────────────────
CONTROL_CENTER_URL=https://<YOUR_VM_IP>/
CONTROL_CENTER_USERNAME=admin
CONTROL_CENTER_PASSWORD=<password>
SCHEMA_REGISTRY_URL=https://<YOUR_VM_IP>/sr/
KSQLDB_URL=https://<YOUR_VM_IP>/ksqldb/
KAFKA_CONNECT_URL=https://<YOUR_VM_IP>/connect/
CMF_REST_URL=https://<YOUR_VM_IP>/cmf/
CMF_CLI_URL=https://<YOUR_VM_IP>

# ── On-prem: Flink (pre-provisioned) ─────────────────────────────────────────
FLINK_ENVIRONMENT=flink-env
FLINK_CATALOG=flink-catalog
FLINK_DATABASE=flink-database
FLINK_COMPUTE_POOL=flink-compute-pool

# ── Predictive Maintenance extras ─────────────────────────────────────────────
LINEAR_API_KEY=lin_api_xxxxxxxxxxxxxxxx   # Linear work orders (mock if absent)
LINEAR_TEAM_ID=xxxxxxxx
AGENT_MIN_ANOMALY_SCORE=0.7
DASHBOARD_REFRESH_S=3

# ── Local MySQL (Podman container via start-mysql.sh) ─────────────────────────
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=kafkauser
MYSQL_PASSWORD=kafkapass
MYSQL_DATABASE=kafkadb
MYSQL_ROOT_PASSWORD=rootpass
```

> **Never commit `.env`, `cflt-vsi-key.pem`, or `client.properties`** — they contain credentials.

### 3. Download the Kafka CA cert (on-prem only)

Required once for native Kafka connections to the VM brokers:

```bash
scp -i cflt-vsi-key.pem root@<YOUR_VM_IP>:/var/lib/confluent/kafka-ca.crt ./kafka-ca.crt
```

---

## Environment Switching

All Python scripts read `KAFKA_ENV` from `.env` (or the shell) and route automatically:

| `KAFKA_ENV` | Connects to | Auth |
|---|---|---|
| `cloud` | Confluent Cloud bootstrap server | API key + secret (SASL_SSL) |
| `onprem` | VM brokers `<YOUR_VM_IP>:9094-9096` | `kafka-admin` SASL_SSL + CA cert |

```bash
# Target Confluent Cloud
KAFKA_ENV=cloud python3 scripts/kafka/list_topics.py

# Target on-prem VM
KAFKA_ENV=onprem python3 scripts/kafka/list_topics.py
```

---

## `auth.py` — shared authentication module

Central auth module imported by all scripts and use-case code. Not run directly.

| Function | What it returns |
|---|---|
| `get_env()` | Active environment: `"cloud"` or `"onprem"` |
| `kafka_config(client_id, group_id)` | confluent-kafka config dict for the active env |
| `http_session(base_url_env)` | `requests.Session` + base URL for any HTTPS component |

---

## Utility Scripts

### `manage_topics.py` — create, delete, describe, list topics

```bash
KAFKA_ENV=onprem python3 scripts/kafka/manage_topics.py list
KAFKA_ENV=onprem python3 scripts/kafka/manage_topics.py create bookings --partitions 3
KAFKA_ENV=onprem python3 scripts/kafka/manage_topics.py describe bookings
KAFKA_ENV=onprem python3 scripts/kafka/manage_topics.py delete bookings
```

| Command | What it does |
|---|---|
| `list` | All user topics with partition count and replication factor |
| `describe` | Per-partition leader, replicas, ISR, and non-default config values |
| `create` | Creates the topic; skips gracefully if it already exists |
| `delete` | Deletes after a `y/N` confirmation prompt |

---

### `list_topics.py` — list topics

```bash
KAFKA_ENV=cloud  python3 scripts/kafka/list_topics.py
KAFKA_ENV=onprem python3 scripts/kafka/list_topics.py
```

---

### `cluster_details.py` — cluster metadata

```bash
KAFKA_ENV=cloud  python3 scripts/kafka/cluster_details.py
KAFKA_ENV=onprem python3 scripts/kafka/cluster_details.py
```

Prints broker count, topic count, cluster ID, and per-topic partition details.

---

### `describe_cluster.py` — full cluster description

```bash
KAFKA_ENV=onprem python3 scripts/kafka/describe_cluster.py
```

Prints install path, broker listeners, service endpoint health, and platform version. On-prem additionally queries Control Center REST for cluster info.

---

### `produce.py` — produce to any topic

```bash
# Single JSON message
KAFKA_ENV=onprem python3 scripts/producers/produce.py --topic users \
  --value '{"name":"alice","age":30}'

# From a JSON Lines file
KAFKA_ENV=onprem python3 scripts/producers/produce.py --topic orders --file orders.jsonl

# Send 100 copies (load test)
KAFKA_ENV=onprem python3 scripts/producers/produce.py --topic test \
  --value '{"ping":true}' --repeat 100
```

| Option | What it does |
|---|---|
| `--topic` | Target topic (required) |
| `--key` | Message key |
| `--value` | Single message value (JSON by default) |
| `--file` | JSON Lines file — one value per line |
| `--raw` | Skip JSON validation |
| `--repeat N` | Send the same message N times |

---

### `consumer.py` — consume messages from any topic

```bash
KAFKA_ENV=onprem python3 scripts/kafka/consumer.py --topic users --limit 10
KAFKA_ENV=onprem python3 scripts/kafka/consumer.py --topic users --from-beginning --format json
```

---

### `consumer_groups.py` — consumer group lag and offset management

```bash
KAFKA_ENV=onprem python3 scripts/kafka/consumer_groups.py list
KAFKA_ENV=onprem python3 scripts/kafka/consumer_groups.py lag --group my-group
KAFKA_ENV=onprem python3 scripts/kafka/consumer_groups.py reset \
  --group my-group --topic users --to earliest
```

---

### `topic_tail.py` — live tail of a Kafka topic

```bash
KAFKA_ENV=onprem python3 scripts/kafka/topic_tail.py --topic transit-events --format json
KAFKA_ENV=onprem python3 scripts/kafka/topic_tail.py --topic sensor-readings --timestamps
```

Seeks every partition to the current end offset on startup — only new messages are shown.

---

### `health_check.py` — full platform health check

```bash
KAFKA_ENV=onprem python3 scripts/platform/health_check.py
KAFKA_ENV=onprem python3 scripts/platform/health_check.py --json
```

```
  COMPONENT               STATUS    LATENCY  TARGET / DETAIL
  ──────────────────────  ──────  ─────────  ─────────────────────────────
  Kafka brokers           UP         142 ms  <YOUR_VM_IP>:9094,...
  Control Center          UP          38 ms  https://<YOUR_VM_IP>
  Schema Registry         UP          22 ms  https://<YOUR_VM_IP>/sr
  ksqlDB                  UP          19 ms  https://<YOUR_VM_IP>/ksqldb
  Kafka Connect           UP          21 ms  https://<YOUR_VM_IP>/connect
  CMF REST                UP          24 ms  https://<YOUR_VM_IP>/cmf

  Summary: 6/6 UP
```

---

### `ksql_query.py` — run ksqlDB from the CLI

```bash
KAFKA_ENV=onprem python3 scripts/platform/ksql_query.py "SHOW STREAMS;"
KAFKA_ENV=onprem python3 scripts/platform/ksql_query.py "SELECT * FROM users EMIT CHANGES;" --limit 10
KAFKA_ENV=onprem python3 scripts/platform/ksql_query.py --file my_queries.sql
```

---

### `manage_connectors.py` — Kafka Connect connector management

```bash
KAFKA_ENV=onprem python3 scripts/connectors/manage_connectors.py list
KAFKA_ENV=onprem python3 scripts/connectors/manage_connectors.py describe datagen-users-source
KAFKA_ENV=onprem python3 scripts/connectors/manage_connectors.py pause   datagen-users-source
KAFKA_ENV=onprem python3 scripts/connectors/manage_connectors.py restart datagen-users-source
KAFKA_ENV=onprem python3 scripts/connectors/manage_connectors.py delete  datagen-users-source
```

---

### `publish_booking.py` — publish a booking event

```bash
KAFKA_ENV=onprem python3 scripts/producers/publish_booking.py --booking-id B-0042
```

---

### `start-mysql.sh` — MySQL 8 Podman container

```bash
./scripts/mysql/start-mysql.sh            # start (creates on first run)
./scripts/mysql/start-mysql.sh --status   # connection details
./scripts/mysql/start-mysql.sh --logs     # tail container logs
./scripts/mysql/start-mysql.sh --stop     # stop and remove
```

Creates a sample `bookings` table on first run for use with `mysql_to_kafka.py`.

---

### `mysql_to_kafka.py` — local MySQL → Kafka topic

```bash
KAFKA_ENV=onprem python3 scripts/producers/mysql_to_kafka.py --table orders
KAFKA_ENV=onprem python3 scripts/producers/mysql_to_kafka.py \
  --table orders --tail --watermark-col updated_at --interval 10
```

Reads rows from a local MySQL table and produces each row as a JSON message to a Kafka topic.
`--tail` mode polls every N seconds for rows newer than the last watermark.

---

### `explore.py` — REST explorer (on-prem only)

```bash
KAFKA_ENV=onprem python3 scripts/platform/explore.py              # interactive menu
KAFKA_ENV=onprem python3 scripts/platform/explore.py sr           # Schema Registry
KAFKA_ENV=onprem python3 scripts/platform/explore.py ksql         # ksqlDB
KAFKA_ENV=onprem python3 scripts/platform/explore.py cmf          # Flink environments
KAFKA_ENV=onprem python3 scripts/platform/explore.py all          # run all
```

---

### `register_schema.py` — register an AVRO schema in Schema Registry

Required to make a Kafka topic visible as a typed Flink table in the KafkaCatalog.

```bash
KAFKA_ENV=onprem python3 scripts/platform/register_schema.py --list
KAFKA_ENV=onprem python3 scripts/platform/register_schema.py \
    --topic sensor-readings \
    --fields '[{"name":"machine_id","type":"string"},{"name":"value","type":"double"}]'
KAFKA_ENV=onprem python3 scripts/platform/register_schema.py --topic sensor-readings --show
```

---

### `setup-datagen.sh` — sample data generator

Deploys a kafka-connect-datagen connector on the VM (~1 AVRO record/sec).

```bash
./scripts/datagen/setup-datagen.sh              # deploy users schema
./scripts/datagen/setup-datagen.sh orders       # deploy orders schema
./scripts/datagen/setup-datagen.sh --stop users
./scripts/datagen/setup-datagen.sh --list       # all 38 available schemas
```

Available schemas include: `users` · `orders` · `clickstream` · `transactions` · `stock_trades` · `ratings` · `pageviews` · `shoes` · `pizza_orders` · …

---

## Flink SQL Shell

Open an interactive Flink SQL session directly from your laptop:

```bash
confluent logout   # required if signed in to Confluent Cloud

confluent flink shell \
  --url https://admin:<password>@<YOUR_VM_IP> \
  --environment flink-env \
  --compute-pool flink-compute-pool \
  --catalog flink-catalog \
  --database flink-database \
  --certificate-authority-path kafka-ca.crt
```

> **Common error — `401 Authorization Required`:**
> The credentials must be embedded in `--url` as `https://user:password@host`.
> Do **not** append `/cmf/` to the URL — the CLI adds that path itself.
> Run `confluent logout` first if you are signed in to Confluent Cloud, otherwise
> the CLI ignores the embedded credentials and sends no `Authorization` header.

```sql
SHOW TABLES;                          -- lists Kafka topics registered in Schema Registry
SELECT * FROM `sensor-readings` LIMIT 10;
SELECT machine_id, COUNT(*) AS events
  FROM `sensor-readings`
  GROUP BY machine_id;                -- continuous aggregation
```

---

## On-Prem Platform Quick Reference

| Component | URL | Auth |
|---|---|---|
| Control Center (web UI) | `https://<YOUR_VM_IP>/` | Basic (`admin` / password) |
| Schema Registry | `https://<YOUR_VM_IP>/sr/` | Basic |
| ksqlDB REST | `https://<YOUR_VM_IP>/ksqldb/` | Basic |
| Kafka Connect | `https://<YOUR_VM_IP>/connect/` | Basic |
| CMF REST | `https://<YOUR_VM_IP>/cmf/` | Basic |
| Kafka brokers | `<YOUR_VM_IP>:9094,9095,9096` | SASL_SSL / `kafka-admin` |

---

## Tutorials

| Tutorial | Focus | Key Topics |
| :--- | :--- | :--- |
| [`01-dsp-introduction.md`](tutorials/01-dsp-introduction.md) | Fundamentals | Data Streaming Platform vs Batch, Kafka concepts, Partitions, Offsets, Consumer Groups. |
| [`02-kora-engine.md`](tutorials/02-kora-engine.md) | Engine Architecture | Kora cloud-native architecture, multi-tenancy, tiered storage, autonomous operations. |
| [`03-flink-cep.md`](tutorials/03-flink-cep.md) | Stream Processing | Complex Event Processing (CEP), tumbling/hopping windows, pattern matching, Flink SQL. |
| [`04-cfk-kubernetes.md`](tutorials/04-cfk-kubernetes.md) | Kubernetes / CFK | **Confluent for Kubernetes (CFK)**, CRDs, KRaft, Domain Connect clusters, S3/DB sinks, OpenShift SCCs, and troubleshooting. |

---

## `scripts/cfk-external-access/` — Level 4 Lab Automation

Automates the **Confluent Level 4: External Client Access to Confluent Platform on Kubernetes** lab end-to-end. All 8 exercises run in sequence from a single command.

### Usage

Run **from the TechZone VM** (the machine with `kubectl` access):

```bash
cd /path/to/confluent-lab
./scripts/cfk-external-access/run_lab.sh

# Override specific values
NAMESPACE=my-ns TOPIC=my-test ./scripts/cfk-external-access/run_lab.sh
./scripts/cfk-external-access/run_lab.sh --skip-cleanup
```

### What it does

| Exercise | What the script does |
|---|---|
| Ex 1 — Explore | Auto-discovers `EXTERNAL_HOST`, `PORT_OFFSET`, `NUM_BROKERS`, `TLS_SECRET`, `PLAIN_SECRET`, `CP_VERSION` from the Kafka CRD |
| Ex 2 — TLS verify | Runs `openssl s_client` against every broker port, checks SAN |
| Ex 3 — Extract | Reads CA cert + `plain-users.json` from Kubernetes secrets |
| Ex 4 — Config | Generates `client.properties` (password never printed) |
| Ex 5 — Docker | Pulls `confluentinc/cp-kafka:$CP_VERSION`, smoke-tests |
| Ex 6 — Topic | Creates test topic across all brokers, checks leader spread |
| Ex 7 — Produce/consume | Produces a timestamped message, consumes and verifies |
| Ex 8 — Control Center | REST API health checks + manual verification checklist |

### Cleanup

```bash
./scripts/cfk-external-access/cleanup.sh
./scripts/cfk-external-access/cleanup.sh --dry-run
./scripts/cfk-external-access/cleanup.sh --keep-workdir
```

---

## `ccloud-python-client/` — Standalone Client Example

```bash
cd ccloud-python-client
python3 -m venv env && source env/bin/activate
pip install -r requirements.txt
python client.py
python client.py --key mykey --value myvalue
```

Reads from `ccloud-python-client/client.properties` instead of environment variables — useful as a self-contained Confluent Cloud example.

---

## Confluent CLI (optional)

```bash
bash cli/install.sh          # downloads CLI binary to bin/
export PATH="$PWD/bin:$PATH"
confluent version
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `confluent-kafka` | Apache Kafka client (librdkafka-based) |
| `python-dotenv` | Load `.env` files into `os.environ` |
| `requests` | HTTP client for Control Center / SR / ksqlDB / Connect / CMF REST APIs |
| `streamlit` | Real-time dashboards for both use cases |
| `pandas` | DataFrame transformations for dashboard tables and charts |
| `plotly` | Interactive charts in Flink analytics pages |
| `mcp` | MCP server SDK for agent tool registration |
| `mysql-connector-python` | `mysql_to_kafka.py` local MySQL reads |
