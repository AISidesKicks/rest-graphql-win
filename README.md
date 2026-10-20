# rest-graphql-win

REST and GraphQL - in observability together they are both clear winners (So we use them BOTH!).

This repo is a runnable lab: the same SaaS support and billing domain is exposed as a
REST API, as a GraphQL API, over SQLite (OLTP) and DuckDB (OLAP), and then wrapped in an
MCP server with a CodeMode sandbox so the token savings of CodeMode can be measured.

- Public landing page: <https://rest.graphql.win>
- Lab chapters: [`lab/`](lab/README.md)
- Design record: [`intent.md`](intent.md)

## Quick start

```bash
pixi run seed      # generate the dataset, deterministic
pixi run etl       # build the DuckDB star schema from SQLite
pixi run serve     # REST, GraphQL and MCP on http://127.0.0.1:8000
```

Then open <http://127.0.0.1:8000/graphql> for GraphiQL and
<http://127.0.0.1:8000/docs> for the REST reference.

## All tasks

| task | what it does |
|---|---|
| `pixi run seed` | Generate the dataset (`--scale large` for the big preset) |
| `pixi run etl` | Materialise the star schema into DuckDB, export Parquet and CSV |
| `pixi run serve` | Serve everything (`--tls` for the mkcert HTTPS path) |
| `pixi run bench` | Compare REST and GraphQL: calls, round trips, ms, rows, bytes |
| `pixi run tools` | Print the MCP catalog with the token cost per tool |
| `pixi run savings` | Native MCP versus CodeMode, offline by default (`--live` for an LLM run) |
| `pixi run verify` | Boot the app and run a REST, GraphQL, MCP and CodeMode pass |
| `pixi run test` | Run the pytest suite |
| `pixi run lint` | Run ruff |

## The stack

FastAPI, Strawberry, SQLite, DuckDB, the MCP Python SDK, Pydantic Monty, tiktoken,
OpenTelemetry and pixi. Everything runs in one environment, one process and one port.

## Credits

The comparison sketches come from the ArjanCodes REST versus GraphQL video, the PostHog
DuckDB versus SQLite article and the CodeMode work around MCP. See
[`docs/index.html`](docs/index.html) for the full list.
