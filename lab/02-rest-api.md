# 02 REST API

FastAPI, prefix `/api`, and a free `/openapi.json` that the MCP catalog is built from
later.

```bash
pixi run serve
```

The interactive reference is at <http://127.0.0.1:8000/docs>.

## The surface

### Operational, SQLite

```
GET    /api/accounts?status=&plan=&segment=&limit=&cursor=
GET    /api/accounts/{id}
GET    /api/accounts/{id}/contacts
PATCH  /api/accounts/{id}
GET    /api/accounts/{id}/tickets?status=&cursor=
GET    /api/tickets?account_id=&status=&priority=&category=&tag=&cursor=
GET    /api/tickets/{id}
GET    /api/tickets/{id}/messages
POST   /api/tickets
PATCH  /api/tickets/{id}
POST   /api/tickets/{id}/messages
POST   /api/tickets/{id}/close
GET    /api/plans
GET    /api/subscriptions?account_id=
GET    /api/subscriptions/{id}
POST   /api/subscriptions/{id}/change_plan
POST   /api/subscriptions/{id}/cancel
GET    /api/invoices?account_id=&status=&cursor=
GET    /api/invoices/{id}
GET    /api/invoices/{id}/lines
GET    /api/invoices/{id}/payments
POST   /api/invoices/{id}/payments
GET    /api/agents?team=
GET    /api/kb/articles?category=&q=
GET    /api/audit/{entity_type}/{entity_id}
```

### Analytical, DuckDB

```
GET    /api/analytics/revenue-by-plan?from=&to=&granularity=
GET    /api/analytics/usage-trends?account_id=&metric=&from=&to=
GET    /api/analytics/tickets-at-risk?threshold=
GET    /api/analytics/top-agents?from=&to=
POST   /api/analytics/query
```

## A walkthrough with curl

### Read a page

```bash
curl -s 'http://127.0.0.1:8000/api/accounts?status=past_due&limit=3' | jq
```

```json
{
  "items": [
    {
      "id": 118,
      "name": "Northwind Robotics",
      "slug": "northwind-robotics",
      "plan_id": 2,
      "status": "past_due",
      "seat_limit": 25,
      "country": "DE",
      "segment": "midmarket",
      "created_at": "2026-03-14T09:12:41+00:00",
      "version": 4
    }
  ],
  "next_cursor": "eyJpZCI6IDExOH0"
}
```

The cursor is a keyset, not an offset. Ask for the next page with:

```bash
curl -s 'http://127.0.0.1:8000/api/accounts?status=past_due&limit=3&cursor=eyJpZCI6IDExOH0'
```

Keyset pagination is used on both API styles, so a REST page and a GraphQL page can be
compared row for row.

### Read one entity, and look at the ETag

```bash
curl -si 'http://127.0.0.1:8000/api/accounts/118' | head -8
```

```
HTTP/1.1 200 OK
etag: "4"
content-type: application/json
```

That `ETag` is the version of the account. It comes back on every single entity read,
and it is what you send back when you want to change it.

### Update with optimistic concurrency

```bash
curl -s -X PATCH 'http://127.0.0.1:8000/api/tickets/456' \
  -H 'Content-Type: application/json' \
  -H 'If-Match: "3"' \
  -d '{"priority": "high"}'
```

If somebody else wrote first, the answer is a `409`:

```json
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "ticket 456 has version 4, the request expected 3",
    "details": {
      "entity": "ticket",
      "id": 456,
      "current_version": 4,
      "expected_version": 3
    }
  }
}
```

The `version` field in the body does the same job, the header is just the REST way of
saying it. If both are present the header wins.

### A missing entity

```bash
curl -s 'http://127.0.0.1:8000/api/accounts/99999999'
```

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "account 99999999 does not exist",
    "details": {"account_id": 99999999}
  }
}
```

Status code `404`, body `{"error": {...}}`. The GraphQL side renders the same rule
differently, that is chapter 04.

### An idempotent write

```bash
curl -s -X POST 'http://127.0.0.1:8000/api/tickets/456/close' \
  -H 'Idempotency-Key: close-ticket-456-1'
```

```json
{
  "ticket_id": 456,
  "status": "closed",
  "version": 4,
  "resolved_at": "2026-06-30T12:00:00+00:00",
  "replayed": false
}
```

Send the exact same request again and nothing happens twice:

```json
{
  "ticket_id": 456,
  "status": "closed",
  "version": 4,
  "resolved_at": "2026-06-30T12:00:00+00:00",
  "replayed": true
}
```

The replayed flag is the proof. And a replay with a different payload under the same key
is a `400` with the code `IDEMPOTENCY_MISMATCH`, because silently doing something else
would be worse than failing.

### The multi table write

```bash
curl -s -X POST 'http://127.0.0.1:8000/api/subscriptions/12/change_plan' \
  -H 'Content-Type: application/json' \
  -H 'If-Match: "2"' \
  -H 'Idempotency-Key: change-plan-12-growth' \
  -d '{"new_plan_code": "growth", "seats": 10}'
```

One call, one SQLite transaction, five tables: the subscription row, the change record,
the invoice, the invoice line and the audit event. If any of them fails, all of them roll
back. Chapter 04 shows how to watch that happen.

### The analytical side

```bash
curl -s 'http://127.0.0.1:8000/api/analytics/tickets-at-risk' | jq '.row_count'
curl -s 'http://127.0.0.1:8000/api/analytics/revenue-by-plan?granularity=month' | jq '.rows[0]'
```

And the allowlisted ad hoc query:

```bash
curl -s -X POST 'http://127.0.0.1:8000/api/analytics/query' \
  -H 'Content-Type: application/json' \
  -d '{"sql": "SELECT plan_code, SUM(amount_cents) AS cents FROM fact_invoice_lines GROUP BY 1"}'
```

The allowlist only accepts `SELECT` and `WITH`, only against the star schema tables, only
one statement, and always with a row cap. Anything else is a `422` with the code
`RULE_VIOLATION`.

## The status codes

| code | when |
| ---- | ---- |
| 200 | the read or the write worked |
| 201 | a resource was created |
| 400 | the idempotency key was reused with a different payload |
| 404 | the entity does not exist |
| 409 | the version does not match, or the state does not allow the change |
| 422 | the payload is not valid, or a business rule says no |

Every error body has the same shape:

```json
{"error": {"code": "...", "message": "...", "details": {...}}}
```

The `code` is stable and machine readable. The `message` is for humans.

Next: [03 GraphQL API](03-graphql-api.md)
