# 08 Code mode

One tool for the model: `exec(code)`. The code runs in Monty, a Rust interpreter for a
Python subset, with no filesystem, no network and no imports. The only way out is the
host functions, and those are the same catalog the native MCP tools publish.

## Why

In native mode the model pays twice:

1. once for the tool schemas, they are in the context on every single turn
2. once for every intermediate payload, because a tool result is text that goes into the
   context

Code mode pays once for a small `exec` schema, and the intermediate payloads stay
inside the sandbox where the model never sees them. Chapter 09 has the numbers.

## The sandbox

Monty, from the Pydantic team: <https://github.com/pydantic/monty>.

```python
from pydantic_monty import Monty

with Monty() as pool:
    with pool.checkout() as session:
        print(session.feed_run("1 + 2"))
```

What the sandbox does not have:

- no `import`, so no `os`, no `socket`, no `subprocess`
- no filesystem access
- no network
- a wall clock limit on the program
- a limit on the number of host calls

What it has: the host functions, and that is it.

## The host functions

One typed Python function per catalog entry:

```python
from tools import list_accounts, list_invoices, list_tickets, graphql_query

accounts = list_accounts(status="past_due", limit=50)
invoices = list_invoices(status="overdue", limit=200)
```

The names are the catalog names with the `rest_` prefix dropped, unless that name is
already taken by a curated tool:

| catalog entry | sandbox function |
| ------------- | ---------------- |
| `rest_list_accounts` | `list_accounts` |
| `rest_list_invoices` | `list_invoices` |
| `rest_change_plan` | `change_plan` |
| `rest_revenue_by_plan` | `rest_revenue_by_plan` |
| `graphql_query` | `graphql_query` |
| `tickets_at_risk` | `tickets_at_risk` |

The stubs are generated from the same OpenAPI document, so the sandbox knows the types:

```
def list_accounts(status: str | None = None, plan: str | None = None, ...) -> Any: ...
```

## The reference program

This is the program from `lab/08-code-mode.md`, it is the one the savings chapter
measures:

```python
invoices = list_invoices(status="overdue", limit=200)
tickets = list_tickets(status="open", priority="critical", limit=200)
accounts = list_accounts(limit=500)
plans = list_plans()

names = {}
for account in accounts["items"]:
    names[account["id"]] = account["name"]

cents = {}
for invoice in invoices["items"]:
    account_id = invoice["account_id"]
    cents[account_id] = cents.get(account_id, 0) + invoice["total_cents"]

critical = {}
for ticket in tickets["items"]:
    account_id = ticket["account_id"]
    critical[account_id] = critical.get(account_id, 0) + 1

rows = []
for account_id in cents:
    if critical.get(account_id, 0) > 0:
        rows.append({
            "account_id": account_id,
            "name": names.get(account_id, "?"),
            "cents": cents[account_id],
        })

rows.sort(key=lambda row: row["cents"], reverse=True)

total = 0
for row in rows:
    total = total + row["cents"]

print("accounts at risk", len(rows))
print("total cents", total)
for row in rows[:10]:
    print(row["account_id"], row["name"], row["cents"])
```

Four host calls, one aggregation, and the model only ever sees the last three lines.

## Running it by hand

The code mode runner is available on the app, so you can drive it without a model:

```bash
pixi run python -c "
import sys; sys.path.insert(0, 'src')
from fastapi.testclient import TestClient
from app import create_app

app = create_app()
with TestClient(app):
    result = app.state.code_mode.run('''
plans = list_plans()
print('plans', len(plans))
''')
    print(result.stdout)
    print('host calls', result.host_calls)
"
```

```
plans 4
host calls 1
```

## Over MCP

The `exec` tool is registered on the MCP server, so any MCP client can use code mode:

```python
result = await session.call_tool(
    "exec",
    {"code": "print(list_plans()[0]['code'])"},
)
```

The tool description is the instruction sheet, it tells the model what the sandbox can
and cannot do.

## The limits

| limit | default | what it protects |
| ----- | ------- | --------------- |
| wall clock | 15 seconds | a runaway program |
| host calls | 200 | a program that hammers the API |
| output size | 64 KB | a program that prints a million rows |

All of them are enforced on the host side, so the sandbox cannot talk its way around
them.

```bash
# the sandbox refuses an import
import socket
```

```
error: ModuleNotFoundError: No module named 'socket'
```

```bash
# and it stops a runaway program
while True:
    pass
```

```
error: TimeoutError: feed time limit exceeded: 15.006919659s > 15s
```

## The traces

A code mode run is one span with a child span per host call:

```
codemode.exec  code_bytes=1146  tools=37  host_calls=4
  mcp.tool.call rest_list_invoices
    http.server GET /api/invoices
      db.query SELECT ...
  mcp.tool.call rest_list_tickets
    ...
```

The whole aggregation is invisible in the trace, because it happens inside the sandbox.
That is the point, and also the trade: you see the calls, not the work.

## What the sandbox is not

- it is not a Python runtime, it is a subset. No imports, limited standard library
- it is not a shell, there is no process to escape into
- it is not a magic bullet for a bad API design. If the API is hard to use, the program
  will be hard to write

That last point matters. Code mode moves the difficulty, it does not remove it. A clean,
well named API makes the generated program short. A messy API makes it long.

Next: [09 Savings](09-savings.md)
