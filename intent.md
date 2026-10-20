# intent.md - the internal design record

This file is the decision record for the lab. It is written before the code, so the
reasoning stays visible while the implementation moves on. The public story lives in
`docs/index.html` and in `lab/`, this file is the honest engineering log.

## 1. What we are building

An educational lab that compares API styles on real numbers instead of opinions:

- **REST** and **GraphQL** over the same domain, backed by the same service layer
- **SQLite** for the operational data and **DuckDB** for the analytical data
- Both API styles wrapped in an **MCP server**
- A **code mode sandbox** on top, so an agent can drive the same catalog with code
  instead of a growing pile of tool payloads
- **OpenTelemetry** traces for every layer, so the claims can be checked

Domain: SaaS support and billing. Accounts, contacts, plans, subscriptions, tickets,
ticket messages, tags, agents, kb articles, invoices, invoice lines, payments, audit events.

## 2. Agreed decisions

| # | Decision | Why |
|---|---|---|
| 1 | Domain is SaaS support and billing | Rich enough for reads, writes, transactions and analytics |
| 2 | REST stack is FastAPI | The free `/openapi.json` is what the MCP catalog is built from |
| 3 | GraphQL stack is Strawberry on FastAPI | SDL first, GraphiQL out of the box, same process |
| 4 | One shared service layer | The comparison has to be about the API style, not about two code bases |
| 5 | Full 2x2 matrix | Every style meets every engine on the same business question |
| 6 | GraphQL writes get a deep dive | Where the two styles really differ: errors, concurrency, idempotency, atomicity |
| 7 | ETL from SQLite to DuckDB | SQLite is the truth, the star schema is a projection of it |
| 8 | Two data presets, `small` and `large` | Small for a fast demo, large to make the engine differences visible |
| 9 | Monty is the code mode sandbox | Rust interpreter, Python subset, host functions as the only bridge |
| 10 | OpenTelemetry everywhere | The same trace proves where the time went |
| 11 | OpenAI compatible agent runner plus an offline harness | The lab must work without an API key |
| 12 | MCP Streamable HTTP mounted at `/mcp` | One process, one port, one URL |
| 13 | MCP exposure switch | The token cost of a tool catalog is a core lesson, so it must be adjustable |
| 14 | One typed Python function per catalog entry | The code mode surface is generated from the same catalog as the MCP tools |
| 15 | mkcert for local TLS | Some MCP clients refuse plain HTTP |
| 16 | Landing page with a live snippet | The page should demonstrate, not describe |
| 17 | pytest plus an end to end verify script | Two levels of checking, one for rules, one for the whole stack |
| 18 | conda-forge for system packages, PyPI for the rest | Never install `pip` into the environment |

## 3. Target architecture

```
                         +---------------------------+
                         |  agent (OpenAI compatible)|
                         +-------------+-------------+
                                       |
                     native MCP        |        code mode
                  (many tool calls)    |     (one exec call)
                                       v
+------------------------------------------------------------------+
|  FastAPI app, one ASGI process, one port                         |
|                                                                  |
|   /api/*            /graphql              /mcp                  |
|   FastAPI routers  Strawberry router     MCPServer              |
|        |                  |                  |                   |
|        +---------+--------+                  |                   |
|                  |                           |                   |
|          +-------v--------+        +---------v---------+         |
|          |  service layer  |        |    MCP catalog    |         |
|          |  (all business  |        |  built from the  |         |
|          |   rules live    |        |  live /openapi   |         |
|          +---+---------+---+        +---------+---------+         |
|              |         |                      |                 |
|       +------v--+  +---v--------+      +------v------+          |
|       | SQLite  |  |   DuckDB   |      | Monty sandbox|          |
|       | (OLTP)  |  |   (OLAP)   |      | host funcs  |          |
|       +---------+  +------------+      +-------------+          |
+------------------------------------------------------------------+
```

The important line in that picture is the service layer. REST and GraphQL are thin
shells over it, so a measured difference comes from the transport and the query
shape, never from duplicated business logic.

## 4. Write semantics, side by side

| Rule | REST | GraphQL |
|---|---|---|
| Entity does not exist | `404` with an error body | `errors[]` with `extensions.code = NOT_FOUND` |
| Optimistic concurrency | `If-Match` header plus `version` in the body, `409` on mismatch | `expectedVersion` argument, same `VERSION_CONFLICT` code |
| Idempotency | `Idempotency-Key` header | `idempotencyKey` argument |
| Idempotency mismatch | `400` with `IDEMPOTENCY_MISMATCH` | same code inside `errors[]` |
| Business rule broken | `422` with `RULE_VIOLATION` | same code inside `errors[]` |
| Partial failure | the request fails as a whole | a non null field bubbles up, a nullable field nulls itself |

Both styles run the same service code, so the same rule produces two different
wire shapes. That contrast is the point of the whole lab.

## 5. Open risks and how we handle them

- **Monty supports a Python subset.** No imports, limited standard library. We keep the
  reference programs inside the subset, document the limits, and keep the runner behind a
  small interface so a second backend can be added later.
- **The MCP SDK and Strawberry move fast.** We pin versions in `pixi.lock` and keep each
  SDK behind one module per concern, so an upgrade touches one file.
- **DuckDB is single writer.** The app opens the database read only, the ETL opens it
  read write under a process wide lock, and the ETL always runs before the app starts.
- **mkcert may be missing on a reader machine.** The serve script prints install
  instructions and falls back to an openssl self signed certificate on another port,
  with a clear warning.
- **LLM endpoints differ in tool calling support.** We only use OpenAI compatible chat
  completions, and the offline harness keeps the lab usable without a key.
- **The large preset is slow to seed.** Small is the default, `--scale large` is opt in,
  and the seeding script prints per table timings.
- **Our own package cannot be called `mcp`.** The MCP Python SDK owns that name and the
  project root is on the import path, so the lab package is `mcplab` and the SDK stays
  `mcp`.

## 6. Out of scope

- GraphQL subscriptions over WebSocket
- Authentication and authorization, a single static API key header would be the next step
- Distributed deployments, containers and a real message broker
- A Phoenix deployment, the OpenTelemetry export path is ready for it and the docker
  setup is documented in the appendix only
