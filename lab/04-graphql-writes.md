# 04 GraphQL writes

This is the chapter where the two API styles really part ways. Everything here is
implemented in one service layer, so both styles run the same rules and only the shape
on the wire changes.

| rule | REST | GraphQL |
| ---- | ---- | ------- |
| the entity does not exist | `404` plus a body | `errors[]` with `extensions.code = NOT_FOUND` |
| the version does not match | `If-Match` header, `409` | `expectedVersion` argument, `VERSION_CONFLICT` |
| a retry | `Idempotency-Key` header | `idempotencyKey` argument |
| a retry with another payload | `400`, `IDEMPOTENCY_MISMATCH` | same code inside `errors[]` |
| a business rule says no | `422`, `RULE_VIOLATION` | same code inside `errors[]` |
| a partial failure | the request fails as a whole | a nullable field nulls itself, a non null field bubbles up |

## The mutations

```graphql
createTicket(input: CreateTicketInput!): Ticket!
updateTicket(id: Int!, input: UpdateTicketInput!, expectedVersion: Int): Ticket!
addTicketMessage(ticketId: Int!, body: String!, authorType: String, authorId: Int): TicketMessage!
closeTicket(ticketId: Int!, expectedVersion: Int, idempotencyKey: String): CloseTicketPayload!
changePlan(subscriptionId: Int!, newPlanCode: String!, seats: Int, expectedVersion: Int, idempotencyKey: String): ChangePlanPayload!
cancelSubscription(id: Int!, expectedVersion: Int): Subscription!
recordPayment(invoiceId: Int!, amountCents: Int!, method: String, idempotencyKey: String): RecordPaymentPayload!
updateAccount(id: Int!, input: UpdateAccountInput!, expectedVersion: Int): Account!
```

## Optimistic concurrency, side by side

The rule: you read an entity, you get its version, you send the version back when you
write. If somebody wrote in between, the write is refused.

### REST

```bash
curl -s 'http://127.0.0.1:8000/api/tickets/456' | jq '.version'
```

```bash
curl -s -X PATCH 'http://127.0.0.1:8000/api/tickets/456' \
  -H 'Content-Type: application/json' \
  -H 'If-Match: "3"' \
  -d '{"priority": "high"}'
```

A stale version:

```json
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "ticket 456 has version 4, the request expected 3",
    "details": {"entity": "ticket", "id": 456, "current_version": 4, "expected_version": 3}
  }
}
```

Status `409`.

### GraphQL

```graphql
mutation Update($id: Int!, $version: Int) {
  updateTicket(id: $id, input: {priority: HIGH}, expectedVersion: $version) {
    id
    version
    priority
  }
}
```

```bash
curl -s -X POST 'http://127.0.0.1:8000/graphql' \
  -H 'Content-Type: application/json' \
  -d '{"query": "mutation Update($id: Int!, $version: Int) { updateTicket(id: $id, input: {priority: HIGH}, expectedVersion: $version) { id version } }", "variables": {"id": 456, "version": 3}}'
```

A stale version:

```json
{
  "data": null,
  "errors": [
    {
      "message": "ticket 456 has version 4, the request expected 3",
      "path": ["updateTicket"],
      "extensions": {
        "code": "VERSION_CONFLICT",
        "details": {"entity": "ticket", "id": 456, "current_version": 4, "expected_version": 3}
      }
    }
  ]
}
```

Status `200`. The rule is identical, the code is identical, only the transport shape
differs. A client that branches on `extensions.code` works on both styles.

### Why the header is the REST way

In REST the version is metadata about the representation, so it belongs in a header. The
`ETag` on the read and the `If-Match` on the write are the HTTP vocabulary for exactly
this. In GraphQL there is no place for request headers in the document, so it becomes an
argument. The `version` field in the request body is a third option, REST accepts it
too, but the header wins when both are there.

## Idempotency, side by side

The rule: a retry of the same logical operation must not do the work twice.

### REST

```bash
curl -s -X POST 'http://127.0.0.1:8000/api/tickets/456/close' \
  -H 'Idempotency-Key: close-456-1'
```

The first answer:

```json
{"ticket_id": 456, "status": "closed", "version": 4, "resolved_at": "...", "replayed": false}
```

The second answer, same key, same payload:

```json
{"ticket_id": 456, "status": "closed", "version": 4, "resolved_at": "...", "replayed": true}
```

### GraphQL

```graphql
mutation Close($id: Int!, $version: Int, $key: String) {
  closeTicket(ticketId: $id, expectedVersion: $version, idempotencyKey: $key) {
    ticketId status version replayed
  }
}
```

Same thing, the key is an argument.

### The mismatch case

Same key, different payload, is an error and not a silent overwrite:

```json
{
  "error": {
    "code": "IDEMPOTENCY_MISMATCH",
    "message": "idempotency key 'close-456-1' was already used with a different payload",
    "details": {"scope": "tickets.close", "key": "close-456-1"}
  }
}
```

The payload is fingerprinted with a SHA-256 over the canonical JSON, so the key and the
payload have to match.

### One detail worth knowing

The replay check happens **before** the business rules. That is not an accident. Without
it, the retry of a close would hit the rule "a closed ticket cannot be closed" and fail,
which is exactly the bug idempotency is supposed to remove. The same applies to the
version check: after the first close the version moved on, so a replay must not be
compared against the new version.

## Atomicity, the multi table mutation

`changePlan` is the interesting write. One call touches five tables:

1. the subscription row, with a new plan and a new seat count
2. the `subscription_changes` record
3. a new invoice for the difference
4. an invoice line that describes the change
5. the audit event

All of it inside one SQLite transaction.

### GraphQL

```graphql
mutation ChangePlan($id: Int!, $plan: String!, $seats: Int, $version: Int, $key: String) {
  changePlan(
    subscriptionId: $id
    newPlanCode: $plan
    seats: $seats
    expectedVersion: $version
    idempotencyKey: $key
  ) {
    subscriptionId fromPlan toPlan seats deltaCents invoiceId version
  }
}
```

```bash
curl -s -X POST 'http://127.0.0.1:8000/graphql' \
  -H 'Content-Type: application/json' \
  -d '{"query": "mutation ChangePlan($id: Int!, $plan: String!, $seats: Int, $version: Int, $key: String) { changePlan(subscriptionId: $id, newPlanCode: $plan, seats: $seats, expectedVersion: $version, idempotencyKey: $key) { subscriptionId fromPlan toPlan seats deltaCents invoiceId version } }", "variables": {"id": 1, "plan": "growth", "seats": 5, "version": 1, "key": "change-1-growth"}}'
```

```json
{
  "data": {
    "changePlan": {
      "subscriptionId": 1,
      "fromPlan": "starter",
      "toPlan": "growth",
      "seats": 5,
      "deltaCents": 75000,
      "invoiceId": 2001,
      "version": 2
    }
  }
}
```

### REST, the same thing

```bash
curl -s -X POST 'http://127.0.0.1:8000/api/subscriptions/1/change_plan' \
  -H 'Content-Type: application/json' \
  -H 'If-Match: "1"' \
  -H 'Idempotency-Key: change-1-growth' \
  -d '{"new_plan_code": "growth", "seats": 5}'
```

Same body, same rules.

### Watch the rollback

Do a second plan change for the same subscription on the same day, without an
idempotency key:

```bash
curl -s -X POST 'http://127.0.0.1:8000/api/subscriptions/1/change_plan' \
  -H 'Content-Type: application/json' \
  -d '{"new_plan_code": "starter", "seats": 4}'
```

```json
{
  "error": {
    "code": "RULE_VIOLATION",
    "message": "a plan change invoice for subscription 1 and 2026-06-30 already exists",
    "details": {"subscription_id": 1, "invoice_number": "CHG-20260630-1"}
  }
}
```

The invoice number is unique, so the insert fails. And now look at the subscription:

```bash
curl -s 'http://127.0.0.1:8000/api/subscriptions/1' | jq '{plan_id, seats, version}'
```

```json
{
  "plan_id": 2,
  "seats": 5,
  "version": 2
}
```

The plan is still `growth` with 5 seats and version 2, exactly as the first change left
it. The second change tried to set `starter` with 4 seats, it updated the subscription
row first, and then the invoice insert failed, so the whole transaction rolled back. The
plan, the seats, the change record and the version are all back where they were.

That is the point: a multi table write is either all of it or none of it.

## Partial failure

GraphQL can answer with partial data. The rule comes from the nullability of the field:

- a **nullable** field that fails becomes `null`, the rest of the answer survives
- a **non null** field that fails bubbles up to the parent, and the parent becomes `null`
  if it is nullable, or the whole answer becomes `null` if it is not

The demo query shows both:

```graphql
{
  partialFailureDemo(failOptional: true) { required optional }
}
```

```json
{
  "data": {"partialFailureDemo": {"required": "the required field worked", "optional": null}},
  "errors": [{"message": "the optional field failed on purpose", "path": ["partialFailureDemo", "optional"]}]
}
```

```graphql
{
  partialFailureDemo(failRequired: true) { required optional }
}
```

```json
{
  "data": {"partialFailureDemo": null},
  "errors": [{"message": "the required field failed on purpose", "path": ["partialFailureDemo", "required"]}]
}
```

REST has no equivalent. A request either returns the body you asked for, or it returns
an error status. There is no "here is most of it".

## What to take away

- the rules are the same, the shapes are not
- `extensions.code` is the bridge: branch on the code and the transport does not matter
- the version and the idempotency key are metadata in REST (headers) and arguments in
  GraphQL
- a multi table write is atomic in both, the transaction does not care about the API
  style
- partial failure is a GraphQL feature REST simply does not have

Next: [05 REST vs GraphQL](05-rest-vs-graphql.md)
