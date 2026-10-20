# 05 REST vs GraphQL

The comparison everybody came for, done with numbers instead of adjectives.

## The measurement

```bash
pixi run bench
```

The reference question again:

> How much revenue is at risk from accounts with an overdue invoice and open critical
> tickets?

```
style       calls  round trips        ms     bytes    rows
----------------------------------------------------------
REST            4            4     22.97    42,689     154
GraphQL         1            1     14.17    14,012     150
GraphQL nested      1            1     14.26     2,428      10
SQLite          1            1      2.96    10,252      50
DuckDB          1            1     20.75    10,252      50

  REST       accounts at risk               6.94 ms    10,812 bytes      50 rows
  REST       overdue invoices               5.48 ms    14,278 bytes      50 rows
  REST       critical open tickets          6.48 ms    17,021 bytes      50 rows
  REST       plans                          3.73 ms       578 bytes       4 rows
  GraphQL    one query, three root fields    14.17 ms    14,012 bytes     150 rows
  GraphQL nested one query, nested fields      14.26 ms     2,428 bytes      10 rows
```

Read that table carefully, because the interesting part is what it does **not** say.

## Round trips

REST needs 4 calls for 4 resources. GraphQL needs 1.

That is the whole argument for GraphQL, and it is a real one: fewer round trips means
less latency, fewer connection setup costs, fewer chances for a flaky network to break
the flow. On a laptop over localhost the difference is small, over a mobile connection
or between two continents it is the difference between one and four times the latency.

The `GraphQL nested` row shows the other shape: one query, nested fields, one account
with its invoices and its tickets. That is the shape REST cannot express without a
client side loop.

## Bytes

REST moves 42,689 bytes, GraphQL moves 14,012 for the same data. GraphQL wins here too,
and the reason is not the format. It is that the REST client asked for 50 accounts, 50
invoices, 50 tickets and 4 plans, and got them. The GraphQL client asked for the same
fields and got the same rows.

The real difference shows up when the two clients ask for different things. A REST
endpoint that returns accounts with contacts, subscription, plan and invoice summary
returns all of that for every account, whether the client needs it or not. That is
over fetching, and it is the default shape of REST.

GraphQL cannot over fetch, the document says exactly which fields are wanted. That is
the strongest argument for the style.

But look at `GraphQL nested`: 2,428 bytes for 10 accounts with their invoices and
tickets. REST with the same data would need one call per account, or an endpoint that
returns a fat account object. The byte count depends on the question, not on the style.

## The N+1 trap

GraphQL does not fix the N+1 problem, it makes it easier to create.

The naive resolver for `Account.tickets` runs one SQL query per account. A list of 50
accounts becomes 51 queries. It is slow, and it is invisible in the response, you only
see it in the traces.

The lab shows both:

```bash
# with the batch loader
curl -s -X POST 'http://127.0.0.1:8000/graphql' -H 'Content-Type: application/json' \
  -d '{"query": "{ accounts(limit: 50) { items { id tickets(limit: 5) { id } } } }"}'

# without it
curl -s -X POST 'http://127.0.0.1:8000/graphql' -H 'Content-Type: application/json' \
  -H 'X-Lab-Batch: off' \
  -d '{"query": "{ accounts(limit: 50) { items { id tickets(limit: 5) { id } } } }"}'
```

Same JSON, very different trace. Chapter 10 shows the trace.

REST has the same trap, it is just called "the client loops over the ids". A REST client
that needs the tickets of 50 accounts makes 51 requests unless the API offers an
endpoint that returns the nested data. Which is, in the end, a hand written version of
a GraphQL query.

## Errors

| | REST | GraphQL |
| --- | --- | --- |
| transport | `404`, `409`, `422` | `200` |
| body | `{"error": {"code", "message", "details"}}` | `{"data": ..., "errors": [{"message", "path", "extensions"}]}` |
| machine readable | the status code, or the code in the body | `extensions.code` |
| partial data | never | yes, when the failed field is nullable |

The practical consequence: naive client code that checks `if response.status == 200`
silently treats a failed GraphQL query as a success. The lab keeps the `extensions.code`
identical to the REST error code, so a client can branch on the rule and not on the
transport.

## Caching

This is where REST wins clearly.

REST is built on HTTP, and HTTP has a caching story:

- every URL is a cache key, `Cache-Control` and `ETag` are part of the protocol
- a CDN can serve `GET /api/accounts/42` without touching your server
- `ETag` plus `If-None-Match` gives you a `304 Not Modified` for free

GraphQL has none of that by default. Every GraphQL query is a `POST` to the same URL, so
a cache sees one URL and cannot tell the queries apart without looking at the body. That
is why GraphQL servers add a persisted query layer or a normalised cache, and why
Apollo and Relay ship their own caching.

The GraphQL side of this lab does not implement a normalised cache. That is a real
limitation and worth naming: for a public, read heavy, mostly identical API, REST with
good cache headers is genuinely easier to run.

## Versioning

REST versions in the URL: `/api/v1/tickets`. It is ugly, but it is obvious. A client
knows what it is talking to, an old version stays alive, and the two can run side by
side.

GraphQL versions in the schema: a field gets deprecated, then removed. That works well
while the change is additive. It hurts when you need to change the meaning of a field,
because then every client has to change at the same time.

GraphQL is better at additive change (new fields, new arguments, new types) and worse at
breaking change. REST is worse at additive change (every new field is a new endpoint or
a fat object) and better at breaking change.

## Over fetching and under fetching

Three kinds of waste:

- **over fetching**: the client gets fields it never reads. REST defaults to this.
- **under fetching**: the client needs a field the response does not have, so it makes
  another request. REST does this a lot.
- **chatty**: one request per entity, the N+1 trap.

GraphQL removes over fetching and under fetching by construction. It does not remove
chatty, that is up to the resolver and the batch loader.

## What to pick

Pick REST when:

- the API is mostly reads with a simple shape
- you want the cache and the CDN
- you want the whole HTTP vocabulary, status codes, headers, ETags
- the clients are many and the contract should be obvious to every one of them

Pick GraphQL when:

- the client needs different slices of the same data
- the screens are many and the data is a graph
- one round trip matters more than one simple URL
- you can afford to run a batch loader and to think about the N+1 trap

And do not forget the third option, which this lab also measures: an agent does not care
about your REST design at all. It cares about how many tokens the tool schemas cost and
how many payloads land in its context. That is
[chapter 09](09-savings.md).

Next: [06 OLTP vs OLAP](06-oltp-vs-olap.md)
