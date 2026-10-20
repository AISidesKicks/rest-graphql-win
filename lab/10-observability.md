# 10 Observability

Every layer of the lab writes spans. That is what turns "I think it is faster" into a
number.

## Where the traces go

```bash
pixi run serve
ls scratch/traces/
```

```jsonl
{"name": "http.server", "trace_id": "...", "span_id": "...", "parent_span_id": "...", "duration_ms": 6.94, "attributes": {"method": "GET", "path": "/api/accounts", "http.status_code": 200}, "status": {"code": "UNSET"}, "events": []}
```

One JSON object per line, one file per run. The exporter is a small class in
`src/observability/tracing.py`, about forty lines, so the format stays readable.

If you have an OTLP backend, point the lab at it:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4317 pixi run serve
```

That is the path to Arize Phoenix, or any other OTLP collector. The spans are the same,
they just travel twice.

## The spans

| span | where it comes from |
| ---- | ------------------ |
| `http.server` | the FastAPI middleware, one per request |
| `service.accounts.list` | the service layer |
| `service.tickets.close` | the service layer |
| `db.query` | the repositories, with the SQL text |
| `mcp.tool.call` | one per MCP tool call |
| `codemode.exec` | one per CodeMode run |
| `agent.turn` | one per agent run |

The nesting is the point. A tool call contains an HTTP request, the HTTP request
contains the service call, the service call contains the SQL.

## A REST call

```bash
curl -s 'http://127.0.0.1:8000/api/accounts?status=past_due&limit=50' > /dev/null
```

```
http.server                     6.94 ms   GET /api/accounts
  service.accounts.list         6.81 ms   status=past_due limit=50
    db.query                    6.55 ms   SELECT a.* FROM accounts a JOIN plans p ...
```

## A GraphQL query

```bash
curl -s -X POST 'http://127.0.0.1:8000/graphql' -H 'Content-Type: application/json' \
  -d '{"query": "{ accounts(limit: 50) { items { id name tickets(limit: 5) { id } } } }"}' > /dev/null
```

```
http.server                    14.20 ms   POST /graphql
  db.query                     2.10 ms   SELECT a.* FROM accounts a ...
  db.query                     1.80 ms   SELECT * FROM tickets WHERE account_id IN (...)
```

Two SQL queries for 50 accounts and their tickets. That is the batch loader doing its
job.

Now the same query with the batch loader switched off:

```bash
curl -s -X POST 'http://127.0.0.1:8000/graphql' -H 'Content-Type: application/json' \
  -H 'X-Lab-Batch: off' \
  -d '{"query": "{ accounts(limit: 50) { items { id name tickets(limit: 5) { id } } } }"}' > /dev/null
```

```
http.server                   181.40 ms   POST /graphql
  db.query                     2.10 ms   SELECT a.* FROM accounts a ...
  db.query                     2.60 ms   SELECT * FROM tickets WHERE account_id = 1
  db.query                     2.50 ms   SELECT * FROM tickets WHERE account_id = 2
  db.query                     2.40 ms   SELECT * FROM tickets WHERE account_id = 3
  ... 50 of them
```

Same JSON in the response, ten times the queries. This is the N+1 trap, visible. The
batch loader is in `src/api/graphql/loaders.py`, it is about thirty lines.

## A CodeMode run

```bash
pixi run python -c "
import sys; sys.path.insert(0, 'src')
from fastapi.testclient import TestClient
from app import create_app
app = create_app()
with TestClient(app):
    app.state.code_mode.run('''
plans = list_plans()
accounts = list_accounts(status='past_due', limit=3)
print('done')
''')
"
```

```
codemode.exec                 31.20 ms   code_bytes=88 tools=37 host_calls=2
  mcp.tool.call rest_list_plans      4.10 ms
    http.server               3.90 ms   GET /api/plans
      service...              3.60 ms
        db.query              3.40 ms   SELECT * FROM plans ORDER BY id
  mcp.tool.call rest_list_accounts   22.80 ms
    http.server              22.40 ms   GET /api/accounts?status=past_due&limit=3
      service.accounts.list  22.10 ms
        db.query             21.80 ms   SELECT a.* FROM accounts a ...
```

Note what is **not** there: the aggregation inside the sandbox. The sandbox is a black
box for the tracer, it does not report the work it does. That is both a feature (the
model does not pay for it) and a limitation (you cannot see how long the aggregation
took).

## Reading a trace by hand

The JSONL format is plain, so `jq` is enough:

```bash
# the slowest spans of the last run
cat scratch/traces/*.jsonl | jq -s 'sort_by(-.duration_ms)[:10] | .[] | "\(.duration_ms)\t\(.name)"'

# every SQL statement
cat scratch/traces/*.jsonl | jq -r 'select(.name == "db.query") | .attributes["db.statement"]'

# how many SQL queries per trace
cat scratch/traces/*.jsonl | jq -s 'group_by(.trace_id) | map({trace: .[0].trace_id, queries: map(select(.name == "db.query")) | length})'
```

That last one is how you catch an N+1 in production: group the spans by trace and count
the queries.

## Sending the spans to Phoenix

The OTLP exporter is one line of configuration:

```bash
docker run -p 4317:4317 -p 6006:6006 arizephoenix/phoenix:latest
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4317 pixi run serve
```

Then open <http://127.0.0.1:6006> and look at the traces. The lab does not ship a
docker compose file, the appendix explains the setup.

## Why this is in the lab

Because the whole point is measurement. Every claim in the other chapters has a span
behind it:

- the round trip difference is `http.server` spans
- the N+1 difference is `db.query` counts
- the CodeMode difference is `codemode.exec` with its children
- the engine difference is the `db.query` duration on SQLite against DuckDB

Next: [11 Appendix](11-appendix.md)
