SET 'auto.offset.reset' = 'earliest';

CREATE STREAM orders_raw (
  order_id VARCHAR KEY,
  customer_id VARCHAR,
  total_amount DOUBLE,
  currency VARCHAR
) WITH (
  KAFKA_TOPIC = 'orders.created',
  VALUE_FORMAT = 'JSON'
);

CREATE TABLE order_totals AS
  SELECT customer_id, COUNT(*) AS order_count, SUM(total_amount) AS total_spend
  FROM orders_raw
  GROUP BY customer_id
  EMIT CHANGES;

SHOW STREAMS;
SHOW TABLES;
SELECT * FROM order_totals EMIT CHANGES LIMIT 5;