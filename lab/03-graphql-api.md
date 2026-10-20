# 03 GraphQL API

Strawberry on the same FastAPI app, at `/graphql`, with GraphiQL on.

```bash
pixi run serve
```

Open <http://127.0.0.1:8000/graphql>.

## The surface

Queries:

```graphql
accounts(status, plan, segment, limit, cursor): AccountPage
account(id): Account
contacts(accountId): [Contact!]!
tickets(accountId, status, priority, category, tag, limit, cursor): TicketPage
ticket(id): Ticket
ticketWithMessages(id): Ticket
subscription(accountId): Subscription
subscriptionById(id): Subscription
invoices(accountId, status, limit, cursor): InvoicePage
invoice(id): Invoice
agents(team): [Agent!]!
kbArticles(category, q): [KbArticle!]!
plans: [Plan!]!
revenueByPlan(dateFrom, dateTo, granularity): [RevenueByPlanRow!]!
usageTrends(metric, accountId, dateFrom, dateTo): [UsageTrendRow!]!
ticketsAtRisk(threshold, referenceDate): [TicketAtRiskRow!]!
topAgents(dateFrom, dateTo, limit): [TopAgentRow!]!
runSql(sql, params, rowCap): SqlResult!
revenueAtRiskSummary(referenceDate): JSON!
partialFailureDemo(failRequired, failOptional): PartialFailureDemo
```

Mutations live in [04 GraphQL writes](04-graphql-writes.md).

## The same question, one query

REST needs a chain of calls for this, GraphQL needs one:

```graphql
query RevenueAtRisk {
  accounts(status: PAST_DUE, limit: 50) {
    items {
      id
      name
      plan { code monthlyPriceCents }
      invoices(status: OVERDUE, limit: 50) { totalCents dueAt }
      tickets(status: OPEN, priority: CRITICAL, limit: 50) { id subject priority }
    }
  }
}
```

```bash
curl -s -X POST 'http://127.0.0.1:8000/graphql' \
  -H 'Content-Type: application/json' \
  -d '{"query": "query RevenueAtRisk { accounts(status: PAST_DUE, limit: 2) { items { id name plan { code } invoices(status: OVERDUE, limit: 2) { totalCents } } } }"}'
```

## Enums

The GraphQL schema uses enums where REST uses free text:

```graphql
enum TicketStatus { OPEN PENDING RESOLVED CLOSED }
enum TicketPriority { LOW NORMAL HIGH CRITICAL }
enum AccountStatus { ACTIVE TRIAL PAST_DUE SUSPENDED CHURNED }
```

That is a real difference, not a cosmetic one:

- REST accepts `status=past_due` and the service layer decides whether it is a valid
  status. A typo comes back as a `422`.
- GraphQL rejects `status=PAST_DUE_ISH` before the resolver runs, at the schema level.
  The error comes back inside the payload with the GraphQL validation message.

The schema is the contract. In REST the contract is the OpenAPI document plus whatever
the service layer checks.

## The batch loader and the N+1 trap

This is the part that surprises people.

Ask for a list of accounts and their tickets:

```graphql
{
  accounts(limit: 10) {
    items { id name tickets(limit: 5) { id subject } }
  }
}
```

The resolver for `tickets` runs once per account. Without a batch loader that is ten SQL
queries. With the batch loader it is one.

The lab lets you see both, with a header:

```bash
# with the batch loader
curl -s -X POST 'http://127.0.0.1:8000/graphql' \
  -H 'Content-Type: application/json' \
  -d '{"query": "{ accounts(limit: 10) { items { id tickets(limit: 5) { id } } } }"}'

# without it
curl -s -X POST 'http://127.0.0.1:8000/graphql' \
  -H 'Content-Type: application/json' \
  -H 'X-Lab-Batch: off' \
  -d '{"query": "{ accounts(limit: 10) { items { id tickets(limit: 5) { id } } } }"}'
```

Both return the same JSON. The difference shows up in the traces, chapter 10 shows how
to read them.

How it works, in `src/api/graphql/loaders.py`:

1. the resolver asks the loader for the accounts it needs
2. the loader collects the keys of every resolver in the same tick
3. one call into the repository answers all of them
4. the answers are cached for the rest of the request

The loader is a small DataLoader, not the full library. It is about thirty lines, which
is enough to see the idea.

## Errors live in the payload

```bash
curl -s -X POST 'http://127.0.0.1:8000/graphql' \
  -H 'Content-Type: application/json' \
  -d '{"query": "{ account(id: 99999999) { id } }"}'
```

```json
{
  "data": null,
  "errors": [
    {
      "message": "account 99999999 does not exist",
      "locations": [{"line": 1, "column": 3}],
      "path": ["account"],
      "extensions": {"code": "NOT_FOUND", "details": {"account_id": 99999999}}
    }
  ]
}
```

Note the HTTP status: `200`. The request succeeded, the query failed. That is the
biggest practical difference between the two styles, and it is the one that breaks
naive client code.

The `extensions.code` is the same stable code the REST side uses, so a client can branch
on the rule and not on the transport.

## Partial failure, in one query

GraphQL can answer with partial data. A field that fails nulls itself if it is nullable,
and bubbles up to the parent if it is not.

```bash
# a nullable field fails, only that field is null
curl -s -X POST 'http://127.0.0.1:8000/graphql' \
  -H 'Content-Type: application/json' \
  -d '{"query": "{ partialFailureDemo(failOptional: true) { required optional } }"}'
```

```json
{
  "data": {"partialFailureDemo": {"required": "the required field worked", "optional": null}},
  "errors": [{"message": "the optional field failed on purpose", "path": ["partialFailureDemo", "optional"]}]
}
```

```bash
# a non null field fails, the bubble stops at the parent
curl -s -X POST 'http://127.0.0.1:8000/graphql' \
  -H 'Content-Type: application/json' \
  -d '{"query": "{ partialFailureDemo(failRequired: true) { required optional } }"}'
```

```json
{
  "data": {"partialFailureDemo": null},
  "errors": [{"message": "the required field failed on purpose", "path": ["partialFailureDemo", "required"]}]
}
```

The same rule in REST: the request fails as a whole, status `500` or `4xx`, no partial
body.

## The schema is readable

```bash
curl -s 'http://127.0.0.1:8000/graphql/schema' | head -40
```

Or read it in GraphiQL, the schema tab is right there. Compare that with the OpenAPI
document at `/openapi.json`: the GraphQL one describes a graph, the OpenAPI one describes
a list of URLs.

Next: [04 GraphQL writes](04-graphql-writes.md)
