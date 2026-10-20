# 07 The MCP server

One MCP server, mounted in the same FastAPI app at `/mcp`, speaking Streamable HTTP.

```bash
pixi run serve
```

```bash
pixi run tools      # the catalog with the token cost per tool
```

## The catalog is generated, not written

The REST tools are built from the live `/openapi.json` of the running app. That matters
more than it sounds:

- the catalog can never drift away from the API
- a new endpoint shows up as a new tool after a restart, with no extra work
- the argument schemas come from the OpenAPI document, so they are already validated

The code that does it is `src/mcplab/catalog.py`. For every operation it reads the
`operationId`, the parameters and the request body schema, and builds a JSON schema for
the tool arguments.

The GraphQL side gets one tool, `graphql_query(query, variables)`, because a GraphQL
document is a query language, not a fixed set of endpoints.

And there are five curated business tools, ready to use without composing requests:

| tool | what it answers |
| ---- | --------------- |
| `revenue_by_plan` | revenue per plan and period |
| `tickets_at_risk` | accounts with an overdue invoice and open critical tickets |
| `top_agents` | the busiest agents over a period |
| `open_tickets_for_account` | the open tickets of one account |
| `plan_usage_summary` | usage of one account against its plan |

## The catalog

```
exposure: curated, graphql, rest
tools:    37
tokens:   3,766 for the schemas alone

tool                               group       tokens  arguments
---------------------------------------------------------------------------------------------------
rest_update_account                rest           258  account_id, if_match, name, status, seat_lim
rest_update_ticket                 rest           241  ticket_id, if_match, subject, priority, cate
rest_list_tickets                  rest           225  account_id, status, priority, category, tag,
rest_change_plan                   rest           195  subscription_id, if_match, idempotency_key,
rest_list_accounts                 rest           171  status, plan, segment, limit, cursor
rest_create_ticket                 rest           171  account_id, subject, priority, category, con
rest_list_invoices                 rest           149  account_id, status, limit, cursor
rest_list_account_tickets          rest           141  account_id, status, limit, cursor
rest_usage_trends                  rest           138  account_id, metric, from, to
rest_record_payment                rest           133  invoice_id, idempotency_key, amount_cents, m
rest_add_ticket_message            rest           125  ticket_id, body, author_type, author_id
rest_top_agents                    rest           119  from, to, limit
rest_revenue_by_plan               rest           112  from, to, granularity
rest_tickets_at_risk               rest            97  threshold, reference_date
rest_run_sql                       rest            93  sql, params, row_cap
rest_close_ticket                  rest            88  ticket_id, idempotency_key
rest_search_kb_articles            rest            88  category, q
graphql_query                      graphql         88  query, variables
revenue_by_plan                    curated         88  date_from, date_to, granularity
...
```

**3,766 tokens before the model does anything.** That is the number the next chapters
are about.

## The exposure switch

The catalog is big, and a big catalog is expensive. The server therefore has a switch:

```bash
MCP_EXPOSURE=all            # the default, everything
MCP_EXPOSURE=rest           # only the REST tools
MCP_EXPOSURE=graphql        # only the GraphQL tool
MCP_EXPOSURE=curated        # only the five business tools
MCP_EXPOSURE=rest,curated   # a mix
```

Or on the command line:

```bash
pixi run serve -- --mcp curated
```

See what the switch does to the token cost:

```bash
pixi run tools -- --exposure curated
pixi run tools -- --exposure rest
pixi run tools -- --exposure graphql
```

```bash
# and the schemas in full, if you want to read them
pixi run tools -- --schemas
```

A small catalog is not only cheaper, it is also less confusing for the model. A model
with 37 tools has to pick the right one every time. A model with 5 curated tools has a
much easier job, and it gets the aggregated answer instead of raw rows.

## Talking to it

### With an MCP client

The endpoint speaks JSON-RPC over Streamable HTTP at `/mcp`. The handshake:

```bash
curl -s -X POST 'http://127.0.0.1:8000/mcp' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
```

Then `tools/list`, then `tools/call`.

### With the Python SDK

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    async with streamable_http_client("http://127.0.0.1:8000/mcp") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([tool.name for tool in tools.tools])

            result = await session.call_tool(
                "tickets_at_risk", {"threshold": 100000}
            )
            print(result.content[0].text)


asyncio.run(main())
```

### The tools really are the API

A REST tool call goes through the real HTTP surface of the app. The chain in the traces
is:

```
mcp.tool.call rest_list_accounts
  http.server GET /api/accounts
    service.accounts.list
      db.query SELECT ... FROM accounts
```

So a tool call is a REST call is a SQL query. Nothing is faked, and the numbers in
chapter 09 are the numbers of the real API.

## The arguments

Header parameters become ordinary arguments with friendly names:

```python
{
  "name": "rest_change_plan",
  "description": "...",
  "inputSchema": {
    "type": "object",
    "properties": {
      "subscription_id": {"type": "integer"},
      "new_plan_code": {"type": "string"},
      "seats": {"type": "integer"},
      "version": {"type": "integer"},
      "if_match": {"type": "string"},
      "idempotency_key": {"type": "string"}
    },
    "required": ["subscription_id", "new_plan_code"]
  }
}
```

`If-Match` became `if_match`, `Idempotency-Key` became `idempotency_key`. The tool
runner puts them back into the right headers, so the API sees exactly what a REST client
would send.

## What is missing, on purpose

- **no authentication.** A static API key header would be the next step
- **no resources and no prompts.** only tools, the lab is about tool payloads
- **no sampling, no elicitation.** the server does not call the model back

Next: [08 CodeMode](08-code-mode.md)
