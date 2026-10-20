# Lab plan: REST vs GraphQL vs MCP + Code Mode (SaaS support and billing)

## Goal

Build an educational demo lab that shows the pluses and minuses of REST and GraphQL on both an
OLTP engine (SQLite) and an OLAP engine (DuckDB), and then wraps both API styles in an MCP
server with a code mode sandbox so the token and call savings of code mode can be measured.

Everything runs from one pixi environment, one executable engine (one ASGI app, one port).

Deliverables:

- `docs/index.html` - public landing page (rest.graphql.win): hero, high level design, the three
  comparison panels, an architecture diagram, one runnable side by side snippet, links to the lab.
- `lab/*.md` - the lab chapters, each with commands and code, linked from `README.md`.
- `intent.md` (repo root) - the internal design record, dumped before any code is written.
- `src/`, `scripts/`, `tests/`, `pixi.toml` - the runnable lab.

## Agreed decisions (decision record, same content goes into `intent.md`)

1. Domain: SaaS support and billing. Accounts, contacts, plans, subscriptions, tickets, ticket
   messages, tags, agents, kb articles, invoices, invoice lines, payments, audit events.
2. REST stack: FastAPI (free `/openapi.json`, which the MCP part consumes).
3. GraphQL stack: Strawberry on FastAPI (`GraphQLRouter`, GraphiQL enabled).
4. One shared service layer (repositories + services). REST routers and GraphQL resolvers only
   shape the response, so every measured difference comes from the API style, not the code.
5. Full 2x2 matrix: REST and GraphQL each expose the operational (SQLite) schema and the
   analytical (DuckDB) schema.
6. GraphQL writes get a full deep dive: atomic multi table mutations, error shapes
   (200 + `errors` vs 4xx), optimistic concurrency (`expectedVersion` vs `If-Match`), idempotency
   keys, partial failure semantics (non null bubbling).
7. Engine relation: ETL. SQLite is the source of truth, an ETL step materializes the columnar
   fact/dim model into DuckDB.
8. Data volume: two presets, `small` (default) and `large`, one flag: `pixi run seed --scale large`.
   Generated files land in a gitignored `data/` dir, logs and traces in `scratch/`.
9. Sandbox for code mode: Monty (`pydantic-monty`), Rust interpreter, Python subset, host functions
   as the only bridge to the APIs.
10. Observability: OpenTelemetry spans for every HTTP request, GraphQL operation, SQL query, MCP
    tool call and code mode run. JSONL exporter into `scratch/traces/`, optional OTLP endpoint via
    `OTEL_EXPORTER_OTLP_ENDPOINT` for Phoenix or any OTLP backend.
11. Savings proof: an agent runner that speaks the OpenAI chat completions API, so any OpenAI
    compatible endpoint works (OpenAI, OpenRouter, Ollama, vLLM). Plus a deterministic offline
    harness that replays the same task without an LLM so the numbers are reproducible.
12. MCP transport: Streamable HTTP mounted in the same FastAPI app at `/mcp`.
13. MCP exposure switch: `all` (default), `rest`, `graphql`, `curated`, or a comma separated mix,
    via `MCP_EXPOSURE` env var and a `--mcp` flag.
14. Code mode surface: one typed Python function per catalog entry (generated from OpenAPI),
    plus `graphql_query(query, variables)` and the curated tools, registered as Monty host
    functions.
15. HTTPS for picky clients: mkcert local CA, `pixi run serve --tls` serves
    `https://127.0.0.1:8443` with a locally trusted certificate. Plain HTTP on `127.0.0.1:8000`
    stays the default.
16. `docs/index.html`: landing + design + one live snippet (a try it panel that calls the local
    server and falls back to a static snippet when the lab is not running).
17. Validation: pytest for the service layer and mutation semantics, plus `pixi run verify` that
    boots the app and runs a REST + GraphQL + MCP + code mode pass end to end.
18. Dependency installs: conda-forge packages with `pixi add <pkg>`, PyPI only packages with
    `pixi add --pypi <pkg>`.

## Repo layout

```
docs/
  index.html                  landing page (design + panels + live snippet)
  RESTvsGRAPQL.jpeg  OLTPvsOLAP.jpeg  MCPwithCODEMODE.jpeg
lab/
  README.md                   lab index
  00-orientation.md           what we build, the 2x2 matrix, how to run
  01-data-model.md            OLTP schema, ETL, OLAP star schema, seed
  02-rest-api.md              REST surface, curl walkthrough
  03-graphql-api.md           GraphQL read surface, GraphiQL walkthrough
  04-graphql-writes.md        mutation deep dive
  05-rest-vs-graphql.md       style comparison (round trips, N+1, errors, caching, versioning)
  06-oltp-vs-olap.md          engine comparison on the same business question
  07-mcp-server.md            tool catalog, exposure switch, schema token cost
  08-code-mode.md             Monty sandbox, typed functions, example program
  09-savings.md               native vs code mode numbers, LLM and offline harness
  10-observability.md         traces and what they show
  11-appendix.md              mkcert TLS, OpenAI compatible endpoints, troubleshooting
intent.md                     internal design record (first deliverable)
README.md                     entry point, links into lab/
pixi.toml                     one environment, all tasks
src/
  app.py                      the single ASGI app (REST + GraphQL + MCP)
  config.py                   settings, env parsing, MCP exposure switch
  domain/
    models.py                 dataclasses / enums for the domain
    errors.py                 domain errors -> REST status and GraphQL error extensions
  data/
    sqlite_repo.py            OLTP repositories and transactions
    duckdb_repo.py            OLAP repositories (read only connection)
    seed.py                   deterministic generator, CSV out, SQLite load
    etl.py                    SQLite -> DuckDB star schema build
  services/
    accounts.py  tickets.py  subscriptions.py  invoices.py  analytics.py
  api/
    rest/  routers, schemas (pydantic), error handlers
    graphql/  strawberry types, queries, mutations, dataloader lite
  mcp/
    server.py                 FastMCP app, catalog, exposure switch
    catalog.py                build tools from live /openapi.json + curated tools
    codemode.py               Monty sandbox runner, host functions, limits
  agent/
    runner.py                 OpenAI compatible chat completions client + MCP bridge
    tasks.py                  the reference task used in both modes
  observability/
    tracing.py                OTel setup, JSONL exporter, span helpers
scripts/
  seed.py  etl.py  bench.py  savings.py  verify.py  dump_tools.py
tests/
  test_sqlite_repo.py  test_mutations.py  test_catalog.py  test_codemode.py
data/                         gitignored, generated
scratch/                      gitignored, traces and bench output
```

## Data model

OLTP, SQLite (`data/oltp.sqlite`), row store, WAL mode:

- `plans(id, code, name, monthly_price_cents, included_tickets, overage_cents, sla_hours)`
- `accounts(id, name, slug, plan_id, status, seat_limit, country, segment, created_at, version)`
- `contacts(id, account_id, email, name, role, is_primary)`
- `subscriptions(id, account_id, plan_id, status, seats, started_at, renews_at, cancelled_at, version)`
- `tickets(id, account_id, contact_id, subject, status, priority, category, agent_id, created_at,
  updated_at, first_response_at, resolved_at, version)`
- `ticket_messages(id, ticket_id, author_type, author_id, body, created_at)`
- `ticket_tags(ticket_id, tag)`
- `agents(id, name, email, team, active)`
- `kb_articles(id, title, slug, category, body, updated_at)`
- `invoices(id, account_id, subscription_id, number, status, issued_at, due_at, paid_at,
  subtotal_cents, tax_cents, total_cents, version)`
- `invoice_lines(id, invoice_id, description, quantity, unit_price_cents, amount_cents, period_start,
  period_end)`
- `payments(id, invoice_id, amount_cents, method, status, paid_at, reference)`
- `audit_events(id, entity_type, entity_id, kind, actor, payload_json, created_at)` - written by every
  mutating path, REST and GraphQL alike.

OLAP, DuckDB (`data/olap.duckdb`), columnar, built by ETL:

- `dim_date(date, year, quarter, month, month_name, day_of_week)`
- `dim_account(account_id, account_name, plan_code, segment, country)`
- `dim_agent(agent_id, agent_name, team)`
- `fact_usage_daily(account_id, date, tickets_opened, tickets_resolved, first_response_seconds,
  billable_minutes)` - generated volume, the big table
- `fact_invoice_lines(invoice_id, account_id, date, plan_code, category, amount_cents, quantity)`
- `fact_ticket_events(ticket_id, account_id, date, kind, response_seconds)`
- `fact_subscription_changes(subscription_id, account_id, date, from_plan, to_plan, seats, delta_cents)`

Seed (`scripts/seed.py`): deterministic with a fixed seed, writes CSV per table into `data/csv/`
(the blog friendly dataset), then loads SQLite.

| preset | accounts | tickets | ticket messages | invoices | fact_usage_daily rows |
|---|---|---|---|---|---|
| small  | 500      | 5,000   | 25,000           | 2,000    | ~90,000 (500 x 180 days)   |
| large  | 5,000    | 150,000 | 750,000          | 40,000   | ~3,650,000 (5,000 x 730 days) |

ETL (`scripts/etl.py`): read SQLite, write the star schema into DuckDB, also export the fact tables
as Parquet and CSV into `data/` so DuckDB can query the files directly.

DuckDB access: one read only connection for the app, one writer connection for the ETL, guarded by
a lock (DuckDB is single writer).

## Part 1: the APIs

### Shared service layer

`src/services/*` holds every business rule. Repositories own SQL. Services return domain objects.
REST and GraphQL call the same services, so the comparison stays honest.

### REST surface (FastAPI, prefix `/api`)

Operational (SQLite):

- `GET /api/accounts?status=&plan=&segment=&limit=&cursor=`
- `GET /api/accounts/{id}`
- `GET /api/accounts/{id}/tickets?status=&cursor=`
- `GET /api/tickets?account_id=&status=&priority=&category=&tag=&cursor=`
- `GET /api/tickets/{id}`
- `GET /api/tickets/{id}/messages`
- `POST /api/tickets`
- `PATCH /api/tickets/{id}` (body carries `version`, returns 409 on mismatch, `ETag` on read)
- `POST /api/tickets/{id}/messages`
- `POST /api/tickets/{id}/close` (honours `Idempotency-Key`)
- `GET /api/subscriptions?account_id=`
- `POST /api/subscriptions/{id}/change_plan` (multi table transaction)
- `POST /api/subscriptions/{id}/cancel`
- `GET /api/invoices?account_id=&status=&cursor=`
- `GET /api/invoices/{id}`
- `POST /api/invoices/{id}/payments` (honours `Idempotency-Key`)
- `GET /api/agents?team=`
- `GET /api/kb/articles?category=&q=`

Analytical (DuckDB):

- `GET /api/analytics/revenue-by-plan?from=&to=&granularity=`
- `GET /api/analytics/usage-trends?account_id=&metric=&from=&to=`
- `GET /api/analytics/tickets-at-risk?threshold=`
- `GET /api/analytics/top-agents?from=&to=`
- `POST /api/analytics/query` (parameterized SQL, allowlisted clauses, row cap)

Cursor pagination (keyset) on both sides, so REST and GraphQL stay comparable.

### GraphQL surface (Strawberry, `/graphql`, GraphiQL on)

Queries: `accounts`, `account`, `tickets`, `ticket`, `ticketWithMessages` (the N+1 demo),
`subscription`, `invoices`, `invoice`, `agents`, `kbArticles`, plus analytics root
`analytics.revenueByPlan`, `analytics.usageTrends`, `analytics.ticketsAtRisk`,
`analytics.topAgents`, `analytics.runSql`.

Mutations (the deep dive):

- `createTicket(input)`, `updateTicket(id, input, expectedVersion)`,
  `addTicketMessage(ticketId, body)`, `closeTicket(ticketId, expectedVersion, idempotencyKey)`
- `changePlan(subscriptionId, newPlanCode, seats, expectedVersion, idempotencyKey)` - one SQLite
  transaction: subscription update, invoice insert, invoice lines, audit event, subscription
  change record. Any failure rolls the whole thing back.
- `cancelSubscription(id, expectedVersion)`
- `recordPayment(invoiceId, amountCents, method, idempotencyKey)`
- `updateAccount(id, input, expectedVersion)`

Write semantics to implement and document:

- Domain errors map to GraphQL `errors[]` with `extensions.code`
  (`NOT_FOUND`, `VERSION_CONFLICT`, `RULE_VIOLATION`, `IDEMPOTENCY_MISMATCH`) and to REST status
  codes (404, 409, 422, 400). Same rule, different shape: that is the teaching point.
- Optimistic concurrency: GraphQL passes `expectedVersion` as an argument, REST uses the
  `If-Match` header (plus `version` in the body) and answers 409.
- Idempotency: GraphQL takes `idempotencyKey` as an argument, REST uses the `Idempotency-Key`
  header. Replay returns the first result, a different payload with the same key is a mismatch.
- Partial failure: a non null field that fails bubbles to the parent and nulls the query, a
  nullable field only nulls itself. Both behaviours get a dedicated demo query.
- Nested resolvers use a small DataLoader style batch loader so GraphQL does not fall into the
  N+1 trap. The lab shows the same query with and without the batch loader.

### 2x2 matrix

|                | SQLite (OLTP) | DuckDB (OLAP) |
| -------------- | ------------- | -------------- |
| REST           | `/api/*`      | `/api/analytics/*` |
| GraphQL        | `Query.*`     | `Query.analytics.*` |

The reference business question used everywhere in the lab:
"How much revenue is at risk from accounts with an overdue invoice and open critical tickets?"
- REST: 3 to 4 calls (accounts at risk, invoices, tickets, plans), N+1 risk on tickets.
- GraphQL: 1 query with nested fields.
- DuckDB answers it as one scan; SQLite answers it with joins over the operational tables.
- `scripts/bench.py` prints the numbers (calls, round trips, ms, rows, bytes).

## Part 2: MCP and code mode

### MCP server

- FastMCP based, mounted into the same FastAPI app at `/mcp` (Streamable HTTP).
- Catalog built at startup from the live `/openapi.json` (one tool per REST operation, name
  sanitized, arguments derived from the OpenAPI schema), plus `graphql_query(query, variables)`,
  plus curated business tools: `revenue_by_plan`, `tickets_at_risk`, `top_agents`,
  `open_tickets_for_account`, `plan_usage_summary`.
- Exposure switch: `MCP_EXPOSURE=all|rest|graphql|curated` or a comma separated mix, also
  `--mcp` on the CLI. `scripts/dump_tools.py` prints the catalog with a token count per tool
  (tiktoken), which is the baseline number for the savings story.

### Code mode

- One model facing tool: `exec(code: str)`.
- The code runs in Monty (`pydantic-monty`). The sandbox has no filesystem, no network, no
  imports; the only way out is the host functions.
- Host functions: one typed Python function per catalog entry (`list_accounts(status=..., ...)`,
  `get_ticket(id=...)`, `graphql_query(query=..., variables=...)`, plus the curated tools),
  registered with the Monty session. Arguments are validated on the host side.
- Limits: wall clock timeout, max output size, max host calls, no file or env access. Every host
  call is traced.
- Reference program (`lab/08-code-mode.md`): fetch accounts at risk, pull their invoices and
  tickets, aggregate revenue at risk, return only the top 10 rows. The same task in native MCP
  mode returns 4 intermediate payloads into the model context.

### Agent runner

- `src/agent/runner.py`: OpenAI chat completions client. Config via env: `LLM_BASE_URL`,
  `LLM_API_KEY`, `LLM_MODEL` (works with Ollama at `http://127.0.0.1:11434/v1`, OpenRouter,
  OpenAI, vLLM).
- Native mode: MCP tool specs are bridged into OpenAI tool definitions; the model calls them
  directly.
- Code mode: the model gets a single `exec` tool plus the code mode instructions, and writes
  Python that runs in the sandbox.
- `scripts/savings.py` runs both modes on the reference task, offline mode included, and prints
  a table: tool calls, round trips, tokens in schema, tokens in tool results, tokens out, wall
  time, bytes moved. Offline mode uses a rule based planner, so the lab works without any key.

### Observability

- OTel SDK with a JSONL exporter (`scratch/traces/*.jsonl`) and an optional OTLP exporter.
- Spans: `http.server` (REST), `graphql.operation` (+ per resolver child spans), `db.query`
  (sqlite and duckdb, with the SQL text), `mcp.tool.call`, `codemode.exec`, `agent.turn`.
- `lab/10-observability.md` shows one trace of a GraphQL query and one of a REST equivalent, and
  the OTel span of a code mode run, where the whole aggregation shows up as one span with child
  host call spans.

## `docs/index.html`

Style follows the three reference images: two panel comparison cards, blue header on the left,
orange header on the right, bold labels inside bullets, a tinted footer band with the verdict
line. Sections:

1. Hero: promise of the lab, one line, plus the three image panels.
2. The 2x2 matrix as an inline SVG diagram (REST and GraphQL over SQLite and DuckDB, plus the
   MCP and code mode layer on top).
3. One runnable snippet: the same business question in REST and in GraphQL, side by side, with a
   try it panel that calls `http://127.0.0.1:8000` when the lab runs and shows the recorded
   output otherwise. The app needs permissive CORS in dev for this.
4. The three comparison panels as images, captioned with what the lab proves about each.
5. Links into the lab chapters on GitHub, the run commands, the stack list.
6. Credits: ArjanCodes 2022 rest-graphql, PostHog DuckDB vs SQLite, Anthropic code execution with
   MCP, Cloudflare code mode, Arize Phoenix, Pydantic Monty.

No em dashes or en dashes anywhere in the HTML or the lab docs.

## Pixi environment

```toml
[dependencies]           # conda-forge
python = "==3.12"
fastapi, uvicorn, pydantic, httpx, duckdb, pytest, ruff,
opentelemetry-api, opentelemetry-sdk, opentelemetry-exporter-otlp-proto-grpc, cryptography

[pypi-dependencies]      # via: pixi add --pypi <pkg>
strawberry-graphql, mcp, pydantic-monty, tiktoken
```

Tasks:

| task | command |
|---|---|
| `pixi run seed` | `python scripts/seed.py` (add `--scale large`) |
| `pixi run etl` | `python scripts/etl.py` |
| `pixi run serve` | uvicorn on `127.0.0.1:8000` (add `--tls` for mkcert) |
| `pixi run bench` | `python scripts/bench.py` |
| `pixi run tools` | `python scripts/dump_tools.py` |
| `pixi run savings` | `python scripts/savings.py` (add `--live` for the LLM run) |
| `pixi run verify` | `python scripts/verify.py` |
| `pixi run test` | `pytest -q` |

Install rule: conda-forge with `pixi add <pkg>`, PyPI only with `pixi add --pypi <pkg>`. Never
install `pip` into the environment.

## Implementation order

1. `intent.md` in the repo root: the decision record from this plan, plus the target architecture
   and the open risks. Then `README.md` pointing at the lab, and the pixi deps and tasks.
2. `src/domain` (models, errors), `src/data/seed.py`, `scripts/seed.py`: generator, CSV export,
   SQLite load. Verify row counts for both presets.
3. `src/data/sqlite_repo.py`, `src/data/duckdb_repo.py`, `scripts/etl.py`: repositories and the
   ETL that builds the star schema.
4. `src/services/*`: business rules, transactions, error mapping.
5. `src/api/rest`: routers, pydantic schemas, error handlers, pagination, `If-Match`,
   `Idempotency-Key`.
6. `src/api/graphql`: strawberry types, queries, resolvers, batch loader, GraphiQL.
7. `src/api/graphql` mutations plus the write semantics (concurrency, idempotency, atomicity,
   partial failure).
8. `src/observability/tracing.py`: OTel setup and span helpers, wired into every layer.
9. `scripts/bench.py` and the first lab chapters (`00` to `06`).
10. `src/mcp/catalog.py`, `src/mcp/server.py`: tool generation from the live OpenAPI document,
    `graphql_query`, curated tools, exposure switch, mounted at `/mcp`.
11. `src/mcp/codemode.py`: Monty session, typed host functions, limits, traces.
12. `src/agent/*` and `scripts/savings.py`: OpenAI compatible runner, native vs code mode,
    offline harness, the savings tables.
13. `docs/index.html`: landing page, panels, SVG diagram, live snippet, credits.
14. Remaining lab chapters (`07` to `11`), cross links from `README.md` and `lab/README.md`.
15. `tests/` plus `scripts/verify.py`, then the TLS (mkcert) path and the appendix.
16. Small conventional commits along the way (`feat(...)`, `docs(...)`, `chore(...)`, lowercase,
    no em dashes).

## Validation

- `pytest`: repository queries and pagination, transaction rollback on a failing multi table
  mutation, version conflict on both styles, idempotency replay and mismatch, error mapping
  (REST status vs GraphQL extensions), catalog generation (tool names, argument schemas,
  exposure switch), Monty runner (a good program, a program that tries to import os, a program
  that loops forever hitting the timeout).
- `pixi run verify`: boots the app in process, runs a REST list and get, a GraphQL query and a
  GraphQL mutation, an MCP `initialize` plus `tools/list`, and one code mode program, then prints
  the comparison tables. No network access needed.
- Manual checks from the lab docs: `pixi run serve` plus the curl commands, GraphiQL in the
  browser, `pixi run tools` for the schema token count, `pixi run savings` for the numbers.

## Risks and mitigations

- Monty supports a Python subset (no imports, limited stdlib). Mitigation: keep the reference
  programs inside the subset, document the limits, and note in the appendix that the runner is
  behind a small interface so a second backend can be added later.
- MCP SDK and Strawberry APIs move fast. Mitigation: pin exact versions in `pixi.lock` and keep
  the SDK surface in one module per concern.
- DuckDB is single writer. Mitigation: read only connection for the app, writer connection plus a
  lock for ETL, ETL runs before the app starts.
- mkcert may not be installed on a reader machine. Mitigation: clear error with install
  instructions, plus an openssl self signed fallback on a different port and a warning.
- LLM endpoints differ in tool calling support. Mitigation: OpenAI compatible chat completions
  only, plus the offline harness so the lab never depends on a key.
- Large preset is slow to seed. Mitigation: small preset by default, `--scale large` opt in, and
  the seeding script prints timings.

## Out of scope

- GraphQL subscriptions over WebSocket.
- Authentication and authorization (a single static API key header would be the next step).
- Distributed deployments, containers, and a real message broker.
- Phoenix deployment (the OTel export path is ready for it, the docker setup is documented in the
  appendix only).
