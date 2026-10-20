# 01 Data model

Two databases, one truth. SQLite holds the operational data, DuckDB holds a projection
of it that answers analytical questions fast.

## The seed

```bash
pixi run seed                 # the small preset, the default
pixi run seed -- --scale large
```

The generator is deterministic, the same seed and preset always produce the same bytes.
That is what makes the numbers in the later chapters reproducible.

| preset  | accounts | tickets | ticket messages | invoices | fact_usage_daily rows |
| ------- | -------- | ------- | --------------- | -------- | --------------------- |
| small   | 500      | 5,000   | 25,000          | 2,000    | 90,500                |
| large   | 5,000    | 150,000 | 750,000         | 40,000   | 3,650,000             |

Two outputs land in `data/`:

- `data/oltp.sqlite` - the operational database the APIs read and write
- `data/csv/*.csv` - the same tables as plain CSV, one file per table, handy for a blog
  post or for loading the dataset into something else

Nothing generated is committed, `data/` is gitignored.

## The OLTP schema

SQLite in WAL mode, one connection per thread, every write inside a transaction.

| table | what it holds |
| ----- | ------------- |
| `plans` | the four plans, price, included tickets, overage, SLA |
| `accounts` | name, slug, plan, status, seat limit, country, segment, version |
| `contacts` | the people of an account, one primary contact |
| `subscriptions` | plan, status, seats, renewal date, version |
| `tickets` | subject, status, priority, category, agent, timestamps, version |
| `ticket_messages` | the conversation, one row per message |
| `ticket_tags` | many to many, the tags of a ticket |
| `agents` | the support team, name, email, team, active |
| `kb_articles` | the knowledge base |
| `invoices` | number, status, dates, subtotal, tax, total, version |
| `invoice_lines` | the lines of an invoice |
| `payments` | the payments against an invoice |
| `audit_events` | every mutation, written by REST and GraphQL alike |
| `subscription_changes` | the plan change history |
| `idempotency_keys` | the stored answers of the idempotent operations |

Three things are worth noticing:

- **every mutable entity has a `version`**. That is the optimistic concurrency token.
  REST reads it from the `ETag` header, GraphQL takes it as the `expectedVersion`
  argument.
- **every mutating path writes an `audit_events` row**. The audit trail does not care
  which API style made the change.
- **`idempotency_keys` stores the first answer** of an idempotent operation, so a
  retry with the same key replays it instead of doing the work twice.

## The ETL

```bash
pixi run etl
```

SQLite is the source of truth, the ETL materialises a star schema into DuckDB. It reads
SQLite and writes DuckDB, never the other way round.

```
data/oltp.sqlite  ──ETL──>  data/olap.duckdb
                             data/parquet/*.parquet
                             data/olap_csv/*.csv
```

The Parquet and CSV exports are there so DuckDB can also query the files directly,
without the database file.

### The star schema

Dimensions:

| table | columns |
| ----- | ------- |
| `dim_date` | date, year, quarter, month, month_name, day_of_week |
| `dim_account` | account_id, account_name, plan_code, segment, country, seat_limit, sla_seconds |
| `dim_agent` | agent_id, agent_name, team |
| `dim_invoice` | invoice_id, account_id, number, status, issued_date, due_date, total_cents |

Facts:

| table | columns |
| ----- | ------- |
| `fact_usage_daily` | account_id, date, tickets_opened, tickets_resolved, first_response_seconds, billable_minutes |
| `fact_invoice_lines` | invoice_id, account_id, date, plan_code, category, amount_cents, quantity |
| `fact_ticket_events` | ticket_id, account_id, date, kind, response_seconds, priority, status, agent_id |
| `fact_subscription_changes` | subscription_id, account_id, date, from_plan, to_plan, seats, delta_cents |

Two additions to the planned shape are worth calling out, because they show a real
modelling decision:

- **`dim_invoice` carries the invoice status.** Without it, "overdue" would need a join
  back into the operational tables and the analytical scan would stop being a scan.
- **`fact_ticket_events` carries `priority`, `status` and `agent_id`.** The same reason:
  "open critical tickets per agent" has to be one scan, not a join.

That is the trade a fact table always makes: a wider table, fewer joins, faster scans.

### The dense fact table

`fact_usage_daily` has one row per account and per day, so the small preset has
`500 x 181 = 90,500` rows. The ticket counts and the response times come from the
operational data. On days without tickets the table keeps a deterministic baseline
derived from the plan SLA and the seat limit, so the shape of the table never changes.

The important part is the shape: a columnar scan reads only the columns it needs, and
the cost based optimiser can push the filters down before the aggregation happens.

## The engine rules

DuckDB is a single writer database, so:

- the app opens `data/olap.duckdb` **read only**
- the ETL opens it read write, under a process wide lock
- the ETL always runs before the app starts

SQLite follows the same idea from the other side:

- one connection per thread, opened in autocommit mode
- every write goes through `BEGIN IMMEDIATE` under a write lock, so two writers can
  never both start and only fail at commit time

## Try it

```bash
pixi run etl

pixi run python -c "
import sys; sys.path.insert(0, 'src')
from data.duckdb_repo import DuckDbRepo
repo = DuckDbRepo('data/olap.duckdb')
result = repo.revenue_by_plan('2026-01-01', '2026-06-30', 'month')
print(result.rows[:3])
"
```

Next: [02 REST API](02-rest-api.md)
