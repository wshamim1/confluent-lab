# Local Flink Pipeline

A fully self-contained, local streaming pipeline — no Confluent Cloud account required.

```
Python Producer → Kafka → Flink → PostgreSQL → FastAPI → Streamlit Dashboard
```

This folder mirrors the architecture used by the Confluent Cloud predictive maintenance
use case (`usecases/predictive_maintenance/`) but runs entirely on your laptop via Docker.

---

## Architecture

```
┌──────────────────────┐
│  producer/           │
│  local_producer.py   │  4 machines × 3 sensors  ~1 msg/sec/machine
└──────────┬───────────┘
           │ JSON  →  sensor-readings topic
           ▼
┌──────────────────────┐
│  Kafka (KRaft)       │  apache/kafka:4.0.1   localhost:9092
│  container: flink-kafka │
└──────────┬───────────┘
           │ stream
           ▼
┌──────────────────────┐
│  Flink 1.20          │  Web UI: http://localhost:8081
│  flink-jobmanager    │  SQL Gateway: http://localhost:8083
│  flink-taskmanager   │
│                      │
│  jobs/anomaly_sql.sql│  ← Flink SQL (recommended)
│  jobs/sensor_job.py  │  ← PyFlink DataStream API (alternative)
│                      │
│  Tumbling 1-min window per (machine_id, sensor_type)
│  → AVG / MIN / MAX / COUNT
│  → anomaly_score = (max-min)/(avg+ε)
└──────────┬───────────┘
           │ JDBC writes
           ▼
┌──────────────────────┐
│  PostgreSQL 17       │  localhost:5432  db=streaming  user=flink
│  sensor_aggregates   │  all window results
│  equipment_alerts    │  anomaly_score >= 0.8 only
└──────────┬───────────┘
           │ SQL queries
           ▼
┌──────────────────────┐
│  FastAPI             │  http://localhost:8000
│  api/main.py         │  /sensors  /alerts  /summary  /health
└──────────┬───────────┘
           │ HTTP polling
           ▼
┌──────────────────────┐
│  Streamlit           │  http://localhost:8501
│  dashboard/app.py    │  Live charts · Alert table · Machine cards
└──────────────────────┘
```

---

## Folder Structure

```
flink/
├── docker-compose.yml        # Kafka + PostgreSQL + Flink (jobmanager + taskmanager)
├── Dockerfile                # Flink image + Kafka/JDBC/PostgreSQL connector JARs
├── sql/
│   └── init.sql              # PostgreSQL schema (auto-run on first container start)
├── producer/
│   └── local_producer.py     # Standalone sensor producer (no Confluent auth needed)
├── jobs/
│   ├── anomaly_sql.sql       # Flink SQL pipeline (recommended — run in SQL client)
│   └── sensor_job.py         # PyFlink DataStream API job (alternative)
├── api/
│   └── main.py               # FastAPI service reading from PostgreSQL
└── dashboard/
    └── app.py                # Streamlit live dashboard polling FastAPI
```

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Podman | 4.x+ | `brew install podman` then `podman machine init && podman machine start` |
| podman-compose | 1.x+ | `pip install podman-compose` |
| Python | 3.11+ | https://www.python.org |
| pip packages | — | see below |

```bash
pip install kafka-python fastapi uvicorn psycopg2-binary streamlit plotly requests pandas
```

---

## Quickstart

A convenience script [`run.sh`](./run.sh) wraps all `podman compose` commands.
All commands run from the **repo root**.

### Step 1 — Start the stack

```bash
# Build the Flink image (downloads connector JARs — ~2 min on first run)
# then starts Kafka, PostgreSQL, Flink jobmanager + taskmanager
./flink/run.sh start
```

Expected output:
```
NAME                  STATUS
flink-kafka           running (healthy)
flink-postgres        running (healthy)
flink-jobmanager      running
flink-taskmanager     running
```

### Step 2 — Create the Kafka topic

```bash
./flink/run.sh topic
```

Or manually:
```bash
podman exec flink-kafka /opt/kafka/bin/kafka-topics.sh \
  --create --if-not-exists --topic sensor-readings \
  --bootstrap-server localhost:9092 \
  --partitions 3 --replication-factor 1
```

### Step 3 — Verify Flink is up

Open **http://localhost:8081** — you should see:
```
Task Managers: 1
Slots Available: 4
Jobs Running: 0
```

### Step 4 — Start the producer

```bash
# From the repo root
python flink/producer/local_producer.py

# Inject a vibration anomaly on turbine-1
python flink/producer/local_producer.py --inject-anomaly --machine-id turbine-1 --sensor-type vibration
```

### Step 5 — Submit the Flink SQL job

**Option A: Flink SQL client (recommended)**

```bash
./flink/run.sh sql
# Inside the SQL client, paste the contents of flink/jobs/anomaly_sql.sql
```

Or pipe the file directly:
```bash
podman exec -i flink-jobmanager \
  /opt/flink/bin/sql-client.sh --file /dev/stdin \
  < flink/jobs/anomaly_sql.sql
```

**Option B: Flink REST API (SQL Gateway on port 8083)**

```bash
SESSION=$(curl -s -X POST http://localhost:8083/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['sessionHandle'])")

curl -s -X POST "http://localhost:8083/v1/sessions/$SESSION/statements" \
  -H 'Content-Type: application/json' \
  -d '{
    "statement": "SELECT machine_id, sensor_type, AVG(`value`) FROM sensor_readings GROUP BY machine_id, sensor_type"
  }'
```

**Option C: PyFlink DataStream job**

```bash
pip install apache-flink==1.20.0
flink run -py flink/jobs/sensor_job.py -m localhost:8081
```

### Step 6 — Start the FastAPI service

```bash
# From the repo root
uvicorn flink.api.main:app --reload --port 8000
```

Verify: http://localhost:8000/health → `{"status":"ok","db":"connected"}`

Browse auto-generated docs: http://localhost:8000/docs

### Step 7 — Start the dashboard

```bash
# From the repo root
streamlit run flink/dashboard/app.py
```

Open **http://localhost:8501** — live-updating charts appear as Flink writes aggregates
to PostgreSQL and the dashboard polls FastAPI every 5 seconds.

---

## Key URLs

| Service | URL |
|---------|-----|
| Flink Web UI | http://localhost:8081 |
| Flink SQL Gateway | http://localhost:8083 |
| FastAPI (JSON) | http://localhost:8000 |
| FastAPI Swagger docs | http://localhost:8000/docs |
| Streamlit dashboard | http://localhost:8501 |
| PostgreSQL | localhost:5432 (user: flink / pass: flink / db: streaming) |

---

## Useful Commands

```bash
# Tail logs for a specific service
./flink/run.sh logs flink-jobmanager
./flink/run.sh logs flink-taskmanager

# Check running Flink jobs
podman exec flink-jobmanager /opt/flink/bin/flink list -m localhost:8081

# Consume raw sensor events from Kafka
podman exec -it flink-kafka \
  /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic sensor-readings --from-beginning

# Query PostgreSQL directly
podman exec -it flink-postgres psql -U flink -d streaming \
  -c "SELECT machine_id, sensor_type, COUNT(*) FROM sensor_aggregates GROUP BY 1,2;"

podman exec -it flink-postgres psql -U flink -d streaming \
  -c "SELECT * FROM equipment_alerts ORDER BY detected_at DESC LIMIT 10;"

# Stop stack (keeps postgres_data volume)
./flink/run.sh stop

# Stop + wipe the database
./flink/run.sh clean
```

---

## How This Compares to the Confluent Cloud Path

| | This folder (`flink/`) | `usecases/predictive_maintenance/` |
|---|---|---|
| **Kafka** | Local Podman (KRaft) | Confluent Cloud / on-prem CP |
| **Flink** | Local Podman 1.20 | Confluent Cloud Flink (serverless) |
| **Anomaly detection** | Range/spread score (SQL) | `ML_PREDICT('AnomalyDetection')` |
| **Sink** | PostgreSQL | Kafka `equipment-alerts` topic |
| **API layer** | FastAPI (`api/main.py`) | MCP server (direct Kafka consumer) |
| **Auth** | None (localhost) | `auth.py` + `.env` credentials |
| **Agent integration** | None | Bob / WatsonX Orchestrate via MCP |

Use this folder to understand the pipeline shape locally; use `usecases/predictive_maintenance/`
for the full agentic, cloud-connected version.

---

## Troubleshooting

**Podman machine not running**
- Run `podman machine start` before `./flink/run.sh start`. Check with `podman machine list`.

**Flink can't connect to Kafka**
- The Flink containers talk to Kafka via the internal Podman network name `kafka:29092`, not `localhost:9092`. The SQL and PyFlink jobs already use this address. If you change the container name in `docker-compose.yml`, update the bootstrap servers in `jobs/anomaly_sql.sql` and `jobs/sensor_job.py` to match.

**`WARN: No splits assigned` in Flink logs**
- The topic exists but has no messages yet. Start the producer first, then check again after ~30 seconds.

**PostgreSQL `init.sql` not applied**
- The init script only runs on the *first* container start. If the volume already exists from a previous run, destroy it: `./flink/run.sh clean && ./flink/run.sh start`.

**`java.lang.ClassNotFoundException: org.postgresql.Driver`**
- The PostgreSQL JDBC JAR wasn't downloaded into the Flink image. Rebuild: `podman compose -f flink/docker-compose.yml build --no-cache`.

**SQL Gateway port 8083 not responding**
- The SQL Gateway requires explicit activation in Flink 1.20. The `docker-compose.yml` sets `sql-gateway.endpoint.rest.port: 8083` in `FLINK_PROPERTIES` on the jobmanager. Check logs: `./flink/run.sh logs flink-jobmanager`.
