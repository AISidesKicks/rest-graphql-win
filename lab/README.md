# The lab

A runnable lab that compares API styles on numbers instead of opinions.

The domain is SaaS support and billing. The same data is exposed four ways:

|                | SQLite (OLTP)                       | DuckDB (OLAP)                      |
| -------------- | ----------------------------------- | ----------------------------------- |
| REST           | `/api/*`                             | `/api/analytics/*`                 |
| GraphQL        | `Query.*`                            | `Query.analytics.*`                 |
| MCP            | one tool per REST operation         | one tool per analytical operation   |
| CodeMode      | the same catalog as typed functions | the same catalog as typed functions |

## The chapters

| chapter | what is inside |
| ------- | -------------- |
| [00 Orientation](00-orientation.md) | What we build, the 2x2 matrix, how to run it |
| [01 Data model](01-data-model.md) | The OLTP schema, the ETL, the star schema, the seed |
| [02 REST API](02-rest-api.md) | The resource surface and a curl walkthrough |
| [03 GraphQL API](03-graphql-api.md) | The read surface, GraphiQL, the batch loader |
| [04 GraphQL writes](04-graphql-writes.md) | Mutations, atomicity, concurrency, idempotency |
| [05 REST vs GraphQL](05-rest-vs-graphql.md) | Round trips, N+1, errors, caching, versioning |
| [06 OLTP vs OLAP](06-oltp-vs-olap.md) | The same question on two engines |
| [07 MCP server](07-mcp-server.md) | The tool catalog, the exposure switch, schema token cost |
| [08 CodeMode](08-code-mode.md) | The Monty sandbox, typed functions, a reference program |
| [09 Savings](09-savings.md) | Native MCP versus CodeMode, with numbers |
| [10 Observability](10-observability.md) | Traces of a REST call, a GraphQL query and a CodeMode run |
| [11 Appendix](11-appendix.md) | TLS, OpenAI compatible endpoints, troubleshooting |

## Run it

```bash
pixi run seed      # generate the dataset
pixi run etl       # build the DuckDB star schema
pixi run serve     # http://127.0.0.1:8000
```

Then:

- REST reference: <http://127.0.0.1:8000/docs>
- GraphiQL: <http://127.0.0.1:8000/graphql>
- MCP endpoint: <http://127.0.0.1:8000/mcp>

## The numbers, on one screen

```bash
pixi run bench      # REST versus GraphQL versus the two engines
pixi run tools      # the MCP catalog and the token cost per tool
pixi run savings    # native MCP versus CodeMode
pixi run verify     # the whole stack, end to end
pixi run test       # the pytest suite
```

The public landing page lives at <https://rest.graphql.win>, the design record at
[`intent.md`](../intent.md).
