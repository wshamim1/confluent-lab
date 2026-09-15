# Complex Event Processing (CEP) with Apache Flink

## Prerequisites

Familiarity with the following will help before working through this tutorial:

- **Stream processing** — understanding the basics of Flink and Kafka from [Tutorial 01](./01-dsp-introduction.md)
- **Apache Flink** — the role of Flink in the DSP as a real-time computation engine
- **SQL basics** — SELECT, WHERE, PARTITION BY
- **Event time vs processing time** — why timestamps on events matter in streaming systems

---

## Key Concepts Glossary

| Term | Definition |
|---|---|
| **CEP** | Complex Event Processing — detecting meaningful sequences of events across time using predefined patterns. |
| **Pattern** | A definition of the event sequence to detect: which event types, in what order, under what conditions, within what time window. |
| **Pattern Match** | The moment a complete sequence of events satisfies all conditions of a defined pattern. |
| **FlinkCEP** | The CEP library built into Apache Flink, used by both the DataStream Pattern API and MATCH_RECOGNIZE. |
| **MATCH_RECOGNIZE** | An ISO SQL standard clause (December 2016) for expressing CEP patterns in SQL. Available in Flink since version 1.7. |
| **DataStream API** | The programmatic Java/Python API for building Flink jobs, offering the most complete access to CEP capabilities. |
| **WITHIN** | A Flink-specific SQL clause that bounds the time window of a pattern — essential for controlling state size in production. |
| **Contiguity** | How strictly consecutive events in a pattern must be: strict (immediately adjacent), non-strict (other events may appear in between), or non-deterministic. |
| **Missing Event Detection** | Detecting that an expected event did NOT occur within a time window — one of the most important and least understood CEP use cases. |
| **NFAb** | Non-deterministic Finite Automaton — the state machine mechanism Flink uses internally to evaluate patterns across event streams. |
| **Watermark** | A Flink signal that all events up to a certain timestamp have arrived, used to trigger time-based pattern completions and expirations. |

---

## What Is Complex Event Processing?

### Stream Processing vs. CEP — Two Fundamentally Different Questions

Stream processing and CEP are both real-time capabilities of Apache Flink, but they answer entirely different classes of question.

**Stream processing** handles events continuously, one at a time or in windows. It answers questions like:

- What is the average transaction value over the last five minutes?
- How many login attempts has this user made in the last hour?
- What is the running total spend per customer today?

These are stateful, real-time computations, but they operate on individual events or aggregates. They do not look for sequences.

**CEP** answers a fundamentally different class of question:

- Did event A happen, followed by event B within 30 seconds, but not preceded by event C in the last 10 minutes?
- Did this machine emit a temperature spike, then a vibration anomaly, then a pressure deviation — all within a 5-minute window?
- Did a card get used in Berlin, then a contactless payment attempted in London two minutes later?

CEP detects **patterns across multiple events in a defined order within a defined time window**. Think of it as a regular expression engine applied to an event stream instead of a text string. You define the pattern once. Flink evaluates every incoming event against every active pattern continuously. The moment a complete match is found, a result is emitted.

```
Stream Processing                CEP
──────────────────               ──────────────────────────────────
Event 1  ──▶ [aggregate]         Event 1  ──▶ [pattern evaluator]
Event 2  ──▶ [aggregate]         Event 2  ──▶ [pattern evaluator] → No match yet
Event 3  ──▶ [aggregate]         Event 3  ──▶ [pattern evaluator] → No match yet
...                              Event N  ──▶ [pattern evaluator] → MATCH FOUND ✓
Window expires ──▶ OUTPUT        Pattern completes ──▶ OUTPUT
(emits on every window)          (emits only on full sequence match)
```

The architectural implication is significant. In a traditional database, queries run against stored data. In CEP, **data runs against stored queries**. Events that match no active pattern are discarded immediately. This makes CEP extremely efficient at high volumes because irrelevant data never accumulates.

### When Is CEP the Right Tool?

CEP is the right choice when **all three conditions are true**:

1. The business logic involves a **sequence** of events — not just a single event or a windowed count
2. The **ordering and interleaving** of specific event types is part of what makes the pattern significant
3. The pattern is **known and deterministic** — you can describe it explicitly in advance

If the pattern is undefined or changes faster than rules can be written, ML-based anomaly detection is more appropriate. If ordering does not matter, a standard windowed aggregation is simpler. More on this in [When NOT to Use Flink CEP](#when-not-to-use-flink-cep).

---

## Missing Event Detection

One of the most valuable and least understood CEP use cases is detecting events that do **not** happen.

Most practitioners instinctively think of event processing as reacting to events that arrive. But some of the most important business signals are **absences**:

- A machine sensor that should emit a heartbeat every 60 seconds goes silent
- A delivery confirmation that should follow a shipment event within four hours never arrives
- A payment settlement that should complete a transaction chain is missing
- An order acknowledgement EDI message that should follow a purchase order within 24 hours never comes

In each case the business needs to know immediately — not after a human notices the gap.

### The Implementation Approach

For missing event detection, a **LEFT JOIN in Flink SQL** is often the more appropriate and more memory-efficient approach than expressing absence as a negative CEP pattern. The query asks: give me all cases where event A arrived but the expected event B never followed within the time window.

```sql
-- Detect shipments with no delivery confirmation within 4 hours
SELECT
    s.shipment_id,
    s.destination,
    s.shipped_at
FROM shipments s
LEFT JOIN deliveries d
    ON s.shipment_id = d.shipment_id
    AND d.confirmed_at BETWEEN s.shipped_at AND s.shipped_at + INTERVAL '4' HOUR
WHERE d.shipment_id IS NULL
```

This is cleaner and more predictable for state management than expressing absence as a complex negative pattern across multiple event types.

### State and Memory Warning

Memory management matters more in missing event detection than in most other CEP patterns. Flink maintains state for every active pattern it is evaluating. A pattern with a 7-day lookback window across high-cardinality keys requires far more memory than one with a 60-minute window.

**Always use `WITHIN` in every pattern definition to bound the time window explicitly.** Without it, state grows unbounded in long-running streaming jobs — one of the most common causes of operational problems in production Flink CEP deployments.

---

## How Flink Implements CEP

Flink provides two complementary approaches to CEP. The right choice depends on pattern complexity and the technical profile of the team.

> **Important note on deployment coverage:** The Pattern API via the DataStream API is available in self-managed Apache Flink, Confluent Platform, and Ververica, but **not** in Confluent Cloud, which exposes Flink exclusively through the SQL and Table API. For teams on Confluent Cloud, **MATCH_RECOGNIZE is the CEP interface available**.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FlinkCEP Library                              │
│        (shared state machine engine used by both approaches)        │
└────────────────────────┬────────────────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          │                             │
          ▼                             ▼
┌──────────────────┐         ┌─────────────────────────┐
│  Pattern API     │         │  MATCH_RECOGNIZE (SQL)  │
│  (DataStream)    │         │  (Table / SQL API)      │
│                  │         │                         │
│  Java / Python   │         │  SQL — ISO standard     │
│  Full CEP        │         │  Accessible to broader  │
│  capability set  │         │  developer audience     │
│                  │         │                         │
│  Available in:   │         │  Available in:          │
│  • OSS Flink     │         │  • OSS Flink            │
│  • Confluent     │         │  • Confluent Cloud      │
│    Platform      │         │  • Confluent Platform   │
│  • Ververica     │         │  • Ververica            │
└──────────────────┘         └─────────────────────────┘
```

### Approach 1 — The Pattern API via the DataStream API

The programmatic approach, available in Java and Python. You define a `Pattern` object specifying the event sequence to detect, chaining conditions with operators:

| Operator | Behaviour |
|---|---|
| `.next("name")` | **Strict contiguity** — the next event in the pattern must immediately follow the previous one with no other events in between |
| `.followedBy("name")` | **Non-strict contiguity** — other events can appear between pattern events; Flink skips non-matching events |
| `.followedByAny("name")` | **Non-deterministic contiguity** — allows multiple matches that differ only in which intermediate events are included |
| `.within(Time.seconds(30))` | Bounds the entire pattern to a time window — **always required in production** |

The `Pattern` is applied to a `DataStream` to create a `PatternStream`, from which matches are extracted using a `PatternProcessFunction`.

**Example — fraud detection pattern in Java:**

```java
Pattern<Transaction, ?> fraudPattern = Pattern
    .<Transaction>begin("first")
        .where(new SimpleCondition<Transaction>() {
            public boolean filter(Transaction t) {
                return t.getAmount() > 500;
            }
        })
    .followedBy("second")
        .where(new SimpleCondition<Transaction>() {
            public boolean filter(Transaction t) {
                return t.getCountry().equals("GB");
            }
        })
    .followedBy("third")
        .where(new SimpleCondition<Transaction>() {
            public boolean filter(Transaction t) {
                return t.getMerchantCategory().equals("ONLINE");
            }
        })
    .within(Time.minutes(10));

PatternStream<Transaction> patternStream =
    CEP.pattern(transactionStream.keyBy(Transaction::getUserId), fraudPattern);

DataStream<Alert> alerts = patternStream.process(
    new PatternProcessFunction<Transaction, Alert>() {
        public void processMatch(
            Map<String, List<Transaction>> match,
            Context ctx,
            Collector<Alert> out
        ) {
            out.collect(new Alert(
                match.get("first").get(0).getUserId(),
                "Suspicious cross-border transaction sequence detected"
            ));
        }
    }
);
```

This approach gives the most complete access to CEP capabilities and maximum flexibility for complex logic. The tradeoff is that DataStream jobs require stronger engineering skills and can become difficult to maintain as pattern complexity grows.

### Approach 2 — MATCH_RECOGNIZE via the SQL and Table API

The SQL approach, based on the ISO SQL:2016 standard. Under the hood it uses the same `FlinkCEP` library as the programmatic API.

#### Core clauses:

| Clause | Purpose |
|---|---|
| `PARTITION BY` | Evaluates the pattern independently per entity (e.g. per user, per machine, per order) |
| `ORDER BY` | Ensures correct event ordering — typically `rowtime` for event-time processing |
| `PATTERN` | Defines the sequence using regular-expression-style syntax (e.g. `(A B+ C)`) |
| `DEFINE` | Maps events to pattern variable names using filter conditions |
| `WITHIN` | (Flink-specific) Bounds the time window — essential for production memory management |
| `MEASURES` | Specifies what to include in the output row when a match is found |

**Example — detecting a multi-step account takeover sequence in SQL:**

```sql
SELECT *
FROM account_events
MATCH_RECOGNIZE (
    PARTITION BY account_id
    ORDER BY event_time
    MEASURES
        FIRST(A.event_time) AS first_seen,
        LAST(C.event_time)  AS completed_at,
        A.account_id        AS account_id
    ONE ROW PER MATCH
    AFTER MATCH SKIP TO NEXT ROW
    PATTERN (A B+ C) WITHIN INTERVAL '5' MINUTE
    DEFINE
        A AS A.event_type = 'PASSWORD_RESET',
        B AS B.event_type = 'FAILED_MFA',
        C AS C.event_type = 'LOGIN_SUCCESS'
)
```

This pattern detects any account where a password reset was followed by one or more failed MFA attempts, then a successful login — all within a 5-minute window.

#### PATTERN syntax reference:

| Syntax | Meaning |
|---|---|
| `A B C` | A, then B, then C in strict sequence |
| `A B+` | A, then one or more B events |
| `A B*` | A, then zero or more B events |
| `A B?` | A, then optionally B |
| `A {3}` | Exactly 3 A events |
| `A {2,5}` | Between 2 and 5 A events |
| `(A \| B)` | Either A or B |

The SQL approach is accessible to a broader range of developers, data engineers, and analysts. Its practical limitations relative to the full Pattern API are also a useful constraint: they prevent patterns from becoming so complex they are impossible to debug or maintain. For the majority of business-level CEP requirements, MATCH_RECOGNIZE is sufficient.

---

## Industry Use Cases

CEP is not a niche capability. The following represent industries where sequential pattern detection delivers business value that general stream processing cannot replicate.

### Financial Services — Fraud Detection

Payment fraud is the most mature CEP application in production globally. Modern fraud is almost never a single suspicious event — it is a chain:

```
card used in Berlin ──▶ contactless attempt in London (2 min later)
  ──▶ high-value online transaction (immediately after)
  = physically impossible travel + velocity pattern
  = FRAUD ALERT before money moves
```

More sophisticated patterns chain five or more events: rapid card enumeration, velocity checks across channels, account takeover sequences. The ability to update detection rules in a running job without restart is particularly valuable here — fraud patterns evolve continuously with attacker behavior, and reducing the time between identifying a new attack pattern and deploying a rule to detect it is a direct business impact measure.

### Manufacturing and IoT — Predictive Maintenance

A machine about to fail does not fail suddenly. It emits a multi-sensor signature in the period before failure:

```
subtle temperature rise ──▶ increasing vibration frequency
  ──▶ pressure deviation
  = pre-failure signature
  = maintenance triggered BEFORE failure occurs
```

A single-sensor threshold alert would either miss the pattern entirely or produce too many false positives to be actionable. CEP detects the full multi-event signature reliably. This is the difference between **reactive maintenance** (fixing after failure) and **predictive maintenance** (intervening while there is still time).

Event-driven architectures built on Kafka and Flink are already in production across automotive and industrial manufacturing environments. CEP-based predictive maintenance is a natural and high-value application layer on top of that existing streaming foundation.

### Supply Chain and ERP — Process Monitoring

Business process events from SAP and other ERP systems, B2B integration platforms, and EDI networks create a continuous stream representing the state of operations across the enterprise.

```
PURCHASE_ORDER created
  ──▶ ORDER_ACKNOWLEDGEMENT (within 24h) — expected EDI 855
  ──▶ ADVANCE_SHIP_NOTICE (before delivery) — expected EDI 856
  ──▶ INVOICE (after shipment) — expected EDI 810
  = complete, compliant B2B order cycle
```

If any step is skipped, delayed beyond an SLA, or occurs out of order — across thousands of concurrent orders and trading partner transactions simultaneously — CEP surfaces it the moment it happens. This is categorically more valuable than a batch report that surfaces the deviation 24 hours after it occurred, when the window to intervene has already closed.

### Telecommunications — Network and Fraud Monitoring

Telco was one of the original CEP industries:

- **Network intrusion detection** — sequences of probes, scans, and access attempts that indicate an attack in progress
- **SLA breach monitoring** — detecting degradation sequences across millions of simultaneous connections before the breach is formally triggered
- **Subscription fraud** — sequential call detail record analysis detecting SIM box fraud, roaming abuse, and account sharing patterns

The combination of high event volumes, strict latency requirements, and the sequential nature of the fraud and failure patterns makes this a domain where CEP consistently delivers value that simpler stream processing cannot replicate.

### E-Commerce — Customer Journey Detection

Sequential behavioral patterns are where MATCH_RECOGNIZE in Flink SQL particularly shines, because the patterns sit close to the business domain and can be authored and maintained by analysts.

```sql
-- Detect churn risk: premium subscriber who downgraded after two renewals
PATTERN (PREMIUM RENEWED{2} DOWNGRADE) WITHIN INTERVAL '1' YEAR

-- Detect purchase intent: repeated product page visits without conversion
PATTERN (VIEW{3,} NO_PURCHASE) WITHIN INTERVAL '7' DAY
```

The output feeds real-time personalization engines, retention workflow triggers, or conversion campaign systems — driving action while the customer is still within their decision window.

---

## When NOT to Use Flink CEP

CEP is a powerful tool for the right problems. For the wrong problems it adds operational complexity with no benefit.

### The Pattern Is Undefined or Too Dynamic

If you do not know what sequence you are looking for, or if the relevant patterns change faster than rules can be written and deployed, **ML-based anomaly detection** is the better approach. Let a model learn what normal behavior looks like from historical data and flag statistical deviations — rather than attempting to enumerate every possible bad pattern upfront.

CEP and ML anomaly detection are complementary, not competing:

| | CEP | ML Anomaly Detection |
|---|---|---|
| **Pattern known?** | Yes — explicitly defined | No — learned from data |
| **Pattern stable?** | Yes — changes infrequently | No — adapts automatically |
| **Explainability** | High — rule is auditable | Variable — model-dependent |
| **False positive control** | Precise | Requires threshold tuning |
| **When to use** | Known fraud patterns, compliance rules, process SLAs | Unknown threats, novel behaviors, statistical outliers |

Both approaches run on the same Flink platform and feed the same downstream systems.

### Ordering Does Not Actually Matter

If the pattern is expressible as a windowed aggregation rather than a strict event sequence, a standard Flink windowed stream processing query is **simpler, cheaper, and easier to maintain** than a CEP job.

| Problem | Right tool |
|---|---|
| More than 5 failed logins within 10 minutes | Windowed COUNT in Flink SQL — no CEP needed |
| Failed login, then password reset, then login from new device | CEP — sequence and ordering matter |
| Total spend over $1,000 in a single day | Windowed SUM in Flink SQL — no CEP needed |
| Small purchase, then large purchase, then international wire | CEP — the sequence is the signal |

CEP adds value specifically when **sequence and ordering are part of what makes the pattern significant**. If they are not, a tumbling or sliding window in Flink SQL handles it cleanly without the overhead of CEP state machines.

And if the business action can wait for a scheduled report or nightly batch job, do not build a streaming architecture at all.

### The Lookback Window Is Impractically Long

A pattern that requires tracking state across 7 days of high-cardinality event data consumes significant Flink cluster memory. If the time window is very long and both event volume and key cardinality are high, the state management cost may outweigh the benefit.

Options:
1. **Constrain the window** using the `WITHIN` clause more aggressively
2. **Reduce key cardinality** through pre-aggregation upstream before the CEP job
3. **Reconsider the architecture** — a batch or lambda architecture may be more appropriate for patterns requiring very long lookback windows

---

## Reference Architecture

The architecture below shows the full picture: source systems feed an event ingestion layer, Flink CEP acts as the pattern detector, and downstream consumers react independently to the structured output.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          SOURCE SYSTEMS                                   │
│  ERP · POS · IoT Sensors · Web Events · EDI · Payment Networks           │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    EVENT INGESTION (Apache Kafka)                         │
│  Raw event topics: transactions · sensor-readings · login-events         │
│  Schema Registry: governed, versioned schemas on every topic             │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│               PATTERN DETECTION (Apache Flink / FlinkCEP)                │
│                                                                          │
│  ┌────────────────────────┐     ┌──────────────────────────────────────┐ │
│  │  MATCH_RECOGNIZE (SQL) │     │  DataStream Pattern API (Java/Python)│ │
│  │  (Confluent Cloud,     │     │  (Confluent Platform, Ververica,     │ │
│  │   all Flink deployments│     │   self-managed Flink)                │ │
│  └────────────────────────┘     └──────────────────────────────────────┘ │
│                                                                          │
│  Outputs a structured event (not a direct action) to a Kafka topic       │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                CEP MATCH EVENTS TOPIC (Apache Kafka)                     │
│  equipment-alerts · fraud-signals · sla-breaches · journey-events       │
└──────┬───────────────────┬───────────────────────┬────────────────────────┘
       │                   │                       │
       ▼                   ▼                       ▼
┌────────────┐    ┌─────────────────┐    ┌──────────────────────────┐
│  Alerting  │    │  Workflow /     │    │  AI Agents               │
│  Systems   │    │  Ticketing      │    │  (Agentic Workflows)      │
│            │    │  (Linear, JIRA, │    │                          │
│  PagerDuty │    │   ServiceNow)   │    │  Enrich, decide, act     │
│  Slack     │    │                 │    │  with real-time context  │
└────────────┘    └─────────────────┘    └──────────────────────────┘
```

**The key architectural principle:** The output of a CEP job should be a structured event published to a Kafka topic — **not a direct action or API call embedded in the job itself**. Downstream consumers react independently. This decoupling:

- Keeps the CEP job simple and stable — it detects patterns, nothing more
- Allows multiple consumers to react to the same signal independently
- Lets response logic evolve without touching detection logic
- Makes the system easier to test, debug, and audit

---

## Best Practices

### Always bound patterns with `WITHIN`

Every active pattern consumes Flink state proportional to its complexity and time window. Start with the simplest pattern that captures the business intent, then add complexity only when required by real cases.

```sql
-- ✓ Correct — state is bounded to 10 minutes per account
PATTERN (A B+ C) WITHIN INTERVAL '10' MINUTE

-- ✗ Wrong — state grows unbounded; will cause operational problems in production
PATTERN (A B+ C)
```

### Decouple detection from response

A CEP job that also calls an external risk scoring API, writes to a database, and sends notifications is doing too many things. When any one component needs to change or fails, the entire job is affected.

```
✓ CEP job → Kafka topic "cep-matches" → [alerting consumer]
                                      → [workflow consumer]
                                      → [AI agent consumer]

✗ CEP job → directly calls risk API → writes to DB → sends Slack alert
```

Separate concerns into focused jobs. Each does one thing well and can be updated, scaled, and debugged independently.

### Use `PARTITION BY` for per-entity evaluation

Almost every business CEP pattern is scoped to an entity — a user, a machine, an account, an order. Always partition by the relevant key so Flink evaluates the pattern independently per entity, not globally across all events.

```sql
MATCH_RECOGNIZE (
    PARTITION BY user_id    -- pattern evaluated independently per user
    ORDER BY event_time
    ...
)
```

### Test patterns with bounded inputs first

CEP patterns can be subtle — especially around `AFTER MATCH SKIP` behavior and `{quantifier}` ranges. Test with a small, controlled set of events that covers:

- A clean match
- A partial match that should not fire
- A pattern that expires without matching (tests `WITHIN` behavior)
- Overlapping matches on the same key

### Monitor state backend size in production

Add metrics on Flink's managed state size, keyed by job. A sudden increase in state size after deploying a new pattern often means the `WITHIN` clause is too wide or key cardinality is higher than expected. Catch this early — state growth is much easier to address before it causes checkpoint timeouts or out-of-memory failures.

---

## The UI/UX Reality — CEP Is an Engineering Discipline

Pattern authoring in Apache Flink is fundamentally an engineering task. Writing DataStream API code in Java or Python requires a developer. Writing MATCH_RECOGNIZE SQL lowers the bar significantly but still assumes familiarity with SQL syntax, event time semantics, and the specific constraints of streaming pattern matching.

The legacy proprietary platforms — TIBCO BusinessEvents and Software AG Apama — shipped with visual rule editors and graphical development studios that allowed business analysts to author and maintain CEP rules without engineering involvement. The open-source Flink ecosystem has no mature equivalent today.

**GenAI is beginning to close this gap, partially.** Current LLMs are capable of generating correct MATCH_RECOGNIZE SQL from a natural language description of a pattern. A fraud analyst describing "flag any user who makes more than three transactions over €500 within 10 minutes across different merchants" can get a working SQL pattern from a code-capable LLM today.

The limits are equally real. Generated DataStream API code for complex stateful patterns still requires engineering review before it goes anywhere near production. LLMs can produce syntactically correct Flink code that contains subtle logical errors in time semantics, state handling, or watermark behavior that are not obvious without deep Flink expertise.

The practical forward state: GenAI will reduce but not eliminate the engineering dependency. Business analysts working with well-defined, SQL-expressible patterns will be increasingly served by natural language interfaces embedded in platforms like Confluent Cloud. Complex pattern engineering involving custom DataStream operators, iterative conditions, or deeply stateful logic will remain a developer discipline.

---

## Summary — CEP Decision Framework

| Situation | Recommended Approach |
|---|---|
| Known, deterministic pattern with ordering | **Flink CEP** — MATCH_RECOGNIZE or DataStream Pattern API |
| Unknown pattern, or too dynamic to define explicitly | **ML anomaly detection** on Flink stream processing |
| Count or aggregation within a time window (no ordering) | **Windowed Flink SQL** — no CEP needed |
| Expected event that never arrives | **LEFT JOIN in Flink SQL** — cleaner than negative CEP pattern |
| Lookback > 3 days, high cardinality, high volume | Reconsider — constrain window, pre-aggregate, or use batch |
| Action can wait for a scheduled job | **Batch** — do not build streaming for it |

### The One-Sentence Rule

> CEP is the right tool when you know the pattern, the sequence matters, and you need to detect it the moment it completes.

### CEP vs Stream Processing vs ML — All on One Platform

```
┌──────────────────────────────────────────────────────────────────┐
│                     Apache Flink Platform                         │
│                                                                  │
│  ┌──────────────────┐  ┌───────────────────┐  ┌───────────────┐ │
│  │   Stream         │  │       CEP          │  │   ML / AI     │ │
│  │   Processing     │  │  (FlinkCEP)        │  │   Functions   │ │
│  │                  │  │                   │  │               │ │
│  │  Aggregations    │  │  Pattern API       │  │  Model        │ │
│  │  Joins           │  │  MATCH_RECOGNIZE   │  │  Inference    │ │
│  │  Enrichment      │  │                   │  │  Anomaly      │ │
│  │  Windowing       │  │  Known sequences  │  │  Detection    │ │
│  │                  │  │  Real-time        │  │               │ │
│  │  Unknown         │  │  detection        │  │  Unknown      │ │
│  │  pattern ok      │  │                   │  │  patterns     │ │
│  └──────────────────┘  └───────────────────┘  └───────────────┘ │
│                                                                  │
│        All three run together. All output to Kafka topics.       │
└──────────────────────────────────────────────────────────────────┘
```

The three approaches are not competing alternatives — they are complementary capabilities on the same platform. A production streaming architecture will typically use all three simultaneously: windowed stream processing for continuous aggregations, CEP for known pattern detection, and ML functions for anomaly detection on novel behaviors.

---

## Further Reading

- [Tutorial 01 — DSP Introduction](./01-dsp-introduction.md) — foundational Kafka and Flink concepts
- [Tutorial 02 — Kora Engine](./02-kora-engine.md) — the cloud-native Kafka engine powering Confluent Cloud
- [Apache Flink MATCH_RECOGNIZE documentation](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/table/sql/queries/match_recognize/)
- [Apache Flink CEP library documentation](https://nightlies.apache.org/flink/flink-docs-stable/docs/libs/cep/)
