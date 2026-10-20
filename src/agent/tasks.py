"""The reference task and the two ways to solve it.

The task is the same one the whole lab uses:

    How much revenue is at risk from accounts with an overdue invoice and open
    critical tickets?

The native plan is what a model does with a wall of tools: one call per
resource, every intermediate payload lands in the context. The code mode plan
is one program that does the same work inside the sandbox and returns only the
answer.

Both plans are described here so the offline harness can replay them without a
model, and so the live run has a fair reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REFERENCE_TASK = (
    "How much revenue is at risk from accounts with an overdue invoice and open "
    "critical tickets? Give me the top 10 accounts and the total amount in cents."
)

NATIVE_SYSTEM_PROMPT = (
    "You are an API assistant. Use the tools to answer the question. "
    "Call one tool at a time and read the result before the next call."
)

CODE_MODE_SYSTEM_PROMPT = (
    "You are an API assistant with a code sandbox. Write one Python program that "
    "answers the question using the lab functions, then call exec with that program. "
    "Print only the final answer, keep the output small."
)


@dataclass
class ToolCall:
    """One planned tool call of the offline native plan."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


OFFLINE_NATIVE_PLAN: list[ToolCall] = [
    ToolCall("list_invoices", {"status": "overdue", "limit": 200}),
    ToolCall("list_tickets", {"status": "open", "priority": "critical", "limit": 200}),
    ToolCall("list_accounts", {"limit": 500}),
    ToolCall("list_plans", {}),
]

OFFLINE_NATIVE_ANSWER = (
    "85 accounts are at risk, 35676200 cents in total. "
    "The top 10 accounts are 48, 95, 201, 250, 258 and the rest with 535143 cents each."
)

OFFLINE_CODE_PROGRAM = '''invoices = list_invoices(status="overdue", limit=200)
tickets = list_tickets(status="open", priority="critical", limit=200)
accounts = list_accounts(limit=500)
plans = list_plans()

names = {}
for account in accounts["items"]:
    names[account["id"]] = account["name"]

plan_codes = {}
for plan in plans:
    plan_codes[plan["id"]] = plan["code"]

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
'''

OFFLINE_CODE_ANSWER = (
    "accounts at risk 85\n"
    "total cents 35676200\n"
    "48 Northwind Analytics 713524\n"
    "and 9 more rows in the same shape"
)
