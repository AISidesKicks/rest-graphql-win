# 09 Savings

The chapter the whole lab exists for. Same task, same catalog, two ways to run it.

## The measurement

```bash
pixi run savings
```

```
task: How much revenue is at risk from accounts with an overdue invoice and open critical tickets? Give me the top 10 accounts and the total amount in cents.
mode: offline, rule based planner

metric                     native MCP      code mode       change
-----------------------------------------------------------------
tool calls                        4.0            1.0       -75.0%
round trips                       4.0            1.0       -75.0%
schema tokens                   4,100.0          262.0       -93.6%
payload tokens                 92,915.0           92.0       -99.9%
output tokens                     44.0          294.0      +568.2%
total tokens                   97,059.0          648.0       -99.3%
bytes moved                   232,207.0          298.0       -99.9%
wall time ms                     64.0           46.6        -17.4%

the full catalog is 37 tools, 3,766 tokens of schemas
native MCP pays for all of them, code mode pays for one exec tool
```

Read the numbers one at a time.

## Schema tokens

**4,100 against 262, a 93.6 percent cut.**

In native mode the model carries the description and the argument schema of every tool
in the catalog, on every turn. 37 tools, 3,766 tokens.

In code mode the model carries the description of one tool, `exec`, plus the code mode
instructions: 262 tokens.

The rest of the catalog is still there, it just moved. The host functions inside the
sandbox are free for the model, because the model never sees their schemas.

This is the part people miss. Code mode does not shrink the API, it moves the API
description out of the context window.

## Payload tokens

**92,915 against 92, a 99.9 percent cut.**

This is the bigger number in practice, and it is where the real pain is.

In native mode, four tool calls, four payloads, 232,207 bytes of JSON. All of it goes
into the context. And then the model has to read it, hold it, and write code or SQL
mentally to aggregate it. Every one of those tokens is paid for on every following turn
too, because the context is resent.

In code mode, the same four calls happen inside the sandbox. The model sees 92 tokens:
the answer.

The data never leaves the sandbox. That is the whole trick.

## Output tokens

**44 against 294, the other way around.**

The native plan is short, four tool calls with short arguments. The code mode plan is
a program, and a program is longer than a tool call.

This is the honest cost of code mode: the model has to write the aggregation logic
itself. 294 tokens of output buys 92,823 tokens of payload savings. On any task with
real aggregation, that is not a close call.

It also means code mode wins less on tasks that need no aggregation. "Get me ticket 456"
is one tool call in both modes, and code mode loses, because it paid for a program
instead of a call.

## The totals

**97,059 tokens against 648. 99.3 percent less.**

That is the headline. And it is reproducible, because the offline harness does not use
a model at all.

## The offline harness

```bash
pixi run savings
```

The offline run replays the reference task with a rule based planner:

- **native**: the four planned tool calls, every payload counted with tiktoken
- **code mode**: the reference program, run in the real Monty sandbox, the output counted

No API key, no network, same numbers every time. That matters for a lab: the claim
"code mode is cheaper" should not depend on which model you happened to use.

The counting itself uses `tiktoken` with the `cl100k_base` encoding, the same encoding
the OpenAI models use. If tiktoken cannot load its vocabulary, the counter falls back to
a rough estimate and says so.

## The live run

```bash
LLM_BASE_URL=http://127.0.0.1:11434/v1 \
LLM_MODEL=qwen2.5-coder \
LLM_API_KEY=ollama \
pixi run savings -- --live
```

Any OpenAI compatible endpoint works: Ollama, OpenRouter, OpenAI, vLLM, LM Studio.

In live mode:

- **native**: the MCP tool schemas are bridged into OpenAI tool definitions, the model
  calls them one at a time, every result goes back into the messages
- **code mode**: the model gets the single `exec` tool, writes Python, the sandbox runs
  it, the output goes back into the messages

The numbers are then real measurements of a real model, and they move around. The
direction does not.

## The step by step

```
native MCP steps:
  {"tool": "rest_list_invoices", "arguments": {"status": "overdue", "limit": 200}, "bytes": 56856}
  {"tool": "rest_list_tickets", "arguments": {"status": "open", "priority": "critical", "limit": 200}, "bytes": 67926}
  {"tool": "rest_list_accounts", "arguments": {"limit": 500}, "bytes": 106874}
  {"tool": "rest_list_plans", "arguments": {}, "bytes": 578}
code mode steps:
  {"tool": "exec", "code_bytes": 1146, "host_calls": 4, "bytes": 298}
```

Same four calls. 232,234 bytes versus 298 bytes.

## When code mode is the wrong answer

Honesty belongs in the chapter:

- **the model has to be good enough to write the program.** A weak model writes a
  broken program and burns a turn on it
- **the code is an extra attack surface.** The sandbox is the mitigation, and it is a
  good one, but a tool that executes model written code deserves a proper review
- **simple tasks do not need it.** One lookup, one tool call, code mode is overhead
- **the API still has to be good.** A model cannot write a clean program against a
  confusing API

## The rules of thumb

| situation | pick |
| --------- | ---- |
| many rows, one answer | code mode |
| a handful of rows, the model needs to reason about each | native |
| the tool catalog is large | code mode |
| the task needs one tool call | native |
| the payload is bigger than the answer | code mode |
| you cannot run a sandbox | native |

Next: [10 Observability](10-observability.md)
