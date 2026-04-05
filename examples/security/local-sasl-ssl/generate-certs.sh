#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="$SCRIPT_DIR/certs"

KEYSTORE_PASSWORD="${KEYSTORE_PASSWORD:-changeit}"
TRUSTSTORE_PASSWORD="${TRUSTSTORE_PASSWORD:-changeit}"
KEY_PASSWORD="${KEY_PASSWORD:-changeit}"
DNAME="${DNAME:-CN=localhost, OU=Kafka, O=ConfluentLab, L=Local, ST=Local, C=US}"

mkdir -p "$CERT_DIR"

keytool -genkeypair \
  -alias broker \
  -keyalg RSA \
  -keysize 2048 \
  -validity 365 \
  -keystore "$CERT_DIR/broker.keystore.jks" \
  -storepass "$KEYSTORE_PASSWORD" \
  -keypass "$KEY_PASSWORD" \
  -dname "$DNAME"

keytool -exportcert \
  -alias broker \
  -keystore "$CERT_DIR/broker.keystore.jks" \
  -storepass "$KEYSTORE_PASSWORD" \
  -rfc \
  -file "$CERT_DIR/broker-cert.pem"

keytool -importcert \
  -alias broker \
  -file "$CERT_DIR/broker-cert.pem" \
  -keystore "$CERT_DIR/broker.truststore.jks" \
  -storepass "$TRUSTSTORE_PASSWORD" \
  -noprompt

keytool -importcert \
  -alias broker \
  -file "$CERT_DIR/broker-cert.pem" \
  -keystore "$CERT_DIR/client.truststore.jks" \
  -storepass "$TRUSTSTORE_PASSWORD" \
  -noprompt

cat <<EOF
Generated local certificate assets in:
$CERT_DIR

Files:
- broker.keystore.jks
- broker.truststore.jks
- client.truststore.jks
- broker-cert.pem

Update your local config paths if needed before starting Kafka.
EOF