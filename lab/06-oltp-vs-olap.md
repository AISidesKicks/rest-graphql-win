# 06 OLTP vs OLAP

Two engines, one question. SQLite is the operational database, DuckDB is the analytical
one, and the ETL keeps them in sync.

## The idea

| | SQLite | DuckDB |
| --- | --- | --- |
| shape | row store, row oriented | column store, column oriented |
| good at | many small writes, point reads | big scans, aggregations, joins over history |
| writes | one writer at a time, WAL mode | one writer at a time |
| reads | index lookups | vectorised, reads only the columns it needs |
| planner | index driven | cost based, reorders joins, pushes filters down |

The PostHog article [DuckDB vs SQLite](https://posthog.com/blog/duckdb-vs-sqlite) is the
reference for this chapter, the numbers here come from this lab.

## The same question, two engines

The lab runs the reference question twice:

```bash
pixi run bench
```

```
style       calls  round trips        ms     bytes    rows
----------------------------------------------------------
SQLite          1            1      2.96    10,252      50
DuckDB          1            1     20.75    10,252      50
```

Same 50 rows, same 10,252 bytes. Different engines, different time.

**SQLite wins on the small dataset.** 2.96 ms against 20.75 ms. That is honest and worth
saying out loud, because the usual story says the column store wins.

Why? Two reasons:

- DuckDB pays a fixed cost per query: it starts a thread pool, plans the query, sets up
  the vectorised execution. On a small query that fixed cost dominates.
- SQLite reads the answer straight out of the page cache, the rows it needs are already
  in memory.

Now make the dataset big enough that the fixed cost does not matter:

```bash
pixi run seed -- --scale large
pixi run etl
pixi run bench
```

The small preset has 500 accounts and 2,000 invoices. The large one has 5,000 accounts,
40,000 invoices, 150,000 tickets and 3,650,000 rows in `fact_usage_daily`. The
operational question now has to walk many more rows, and the columnar scan starts to
pay off. The DuckDB query touches a few hundred thousand values in four columns, SQLite
walks index after index over the operational tables.

The lesson is not "DuckDB is faster". The lesson is:

> Pick the engine for the shape of the question, and measure on your data. A columnar
> scan wins when the question touches a lot of rows and few columns. A row store wins
> when the answer is a few rows that live next to each other.

## Why the ETL exists

The operational data is not shaped for analysis:

- an invoice line does not know which plan it belongs to
- a ticket does not know if the account is at risk
- "how much revenue per plan per month" means five joins over the operational tables

A star schema answers it with one scan:

```sql
SELECT date_trunc('month', "date") AS period,
       plan_code,
       SUM(amount_cents) AS revenue_cents,
       COUNT(DISTINCT invoice_id) AS invoices
FROM fact_invoice_lines
WHERE "date" BETWEEN '2026-01-01' AND '2026-06-30'
GROUP BY 1, 2
ORDER BY 1, 2
```

The ETL materialises that shape from SQLite. It runs before the app starts, never
during, because DuckDB is a single writer database:

```bash
pixi run etl
```

```
  dim_date                            181 rows
  dim_account                         500 rows
  dim_agent                            40 rows
  dim_invoice                       2,000 rows
  fact_usage_daily                 90,500 rows
  fact_invoice_lines                6,067 rows
  fact_ticket_events               10,808 rows
  fact_subscription_changes             0 rows
built data/olap.duckdb in 0.30s
```

## What the column store actually does

Three things happen in DuckDB that do not happen in SQLite:

**1. It reads columns, not rows.** A query that needs `plan_code` and `amount_cents`
touches two columns. The other nine columns of the row are never loaded.

**2. It vectorises.** Values are processed in blocks of 2048, so the per value overhead
of the interpreter disappears. SQLite processes one value at a time.

**3. The optimiser reorders the work.** The cost based planner looks at the table
statistics, decides which join order is cheapest, and pushes the filters down before the
aggregation. The `EXISTS` subquery in the operational version becomes a join over a
small dimension.

## The operational version of the same question

For reference, this is what the SQLite side runs:

```sql
SELECT a.id, a.name, p.code, a.segment,
       SUM(i.total_cents) AS overdue_cents,
       COUNT(*) AS overdue_invoices,
       (SELECT COUNT(*) FROM tickets t
         WHERE t.account_id = a.id
           AND t.status IN ('open','pending')
           AND t.priority = 'critical') AS critical_open
FROM accounts a
JOIN invoices i ON i.account_id = a.id
JOIN plans p ON p.id = a.plan_id
WHERE i.status IN ('overdue','open')
  AND i.due_at < ?
  AND EXISTS (SELECT 1 FROM tickets t
               WHERE t.account_id = a.id
                 AND t.status IN ('open','pending')
                 AND t.priority = 'critical')
GROUP BY a.id, a.name, p.code, a.segment
ORDER BY overdue_cents DESC
LIMIT 50
```

Three joins, a correlated subquery, a group by. It works, it is fast enough on the
operational data, and it is exactly the kind of query that gets slow when the table
grows.

## Both at once

The lab exposes the same question through both API styles:

```bash
curl -s 'http://127.0.0.1:8000/api/analytics/tickets-at-risk' | jq '.row_count'
```

```graphql
{
  ticketsAtRisk(referenceDate: "2026-06-30") {
    accountId
    accountName
    planCode
    overdueCents
    criticalOpen
    revenueAtRiskCents
  }
}
```

The GraphQL version is the same DuckDB query with a nicer shape. The REST version is
the same DuckDB query with a URL.

## The rules of the house

- SQLite is the source of truth, nothing writes into DuckDB while the app runs
- the app opens DuckDB **read only**
- the ETL opens it read write, under a process wide lock
- the ETL runs before the app starts
- the Parquet and CSV exports let DuckDB query the files directly, no database needed

## Which one should you use

Use one engine when you can. Two engines mean two things to keep in sync, and the ETL is
the price of admission. The lab pays that price on purpose, so the trade is visible:

- the ETL costs a run of 0.3 seconds on the small preset, and more on the large one
- the analytical queries get fast
- the operational queries stay simple
- and now you know what the alternative looks like

Next: [07 MCP server](07-mcp-server.md)
