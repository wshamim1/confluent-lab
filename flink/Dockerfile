FROM flink:1.20.0-scala_2.12-java17

# ── Kafka SQL connector (fat JAR — bundles kafka-clients, avoids ClassNotFound) ─
# Use flink-sql-connector-kafka (not flink-connector-kafka) for the SQL client.
# The thin connector requires kafka-clients.jar separately; the SQL connector
# bundles everything needed.
RUN wget -q -P /opt/flink/lib \
    https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/4.0.0-2.0/flink-sql-connector-kafka-4.0.0-2.0.jar

# ── JDBC connector ────────────────────────────────────────────────────────────
RUN wget -q -P /opt/flink/lib \
    https://repo1.maven.org/maven2/org/apache/flink/flink-connector-jdbc/3.2.0-1.19/flink-connector-jdbc-3.2.0-1.19.jar

# ── PostgreSQL JDBC driver ────────────────────────────────────────────────────
RUN wget -q -P /opt/flink/lib \
    https://jdbc.postgresql.org/download/postgresql-42.7.7.jar

# ── SQL Gateway (bundled in Flink 1.20, just needs enabling) ──────────────────
# No extra download needed — sql-gateway is part of the Flink distribution.
# It is activated via FLINK_PROPERTIES in docker-compose.yml.
