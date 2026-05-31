# Mocking MCP servers

A mock MCP server stands in for a real service. It speaks JSON-RPC over Streamable-HTTP on a local port, serves a tool schema, holds seeded state, dispatches `tools/call` to either a declarative rule or a Python handler, and **records every call** so `tool_called` assertions work. One `mock.yaml` backs one server.

## Table of contents

- [mock.yaml anatomy](#mockyaml-anatomy)
- [The tool schema](#the-tool-schema)
- [Seed state](#seed-state)
- [Declarative responses](#declarative-responses)
- [Templating](#templating)
- [Mutations](#mutations)
- [handler.py (stateful tools)](#handlerpy-stateful-tools)
- [Declarative vs handler: how to choose](#declarative-vs-handler-how-to-choose)
- [Dispatch order and built-in behavior](#dispatch-order-and-built-in-behavior)

---

## mock.yaml anatomy

Lives at `scenarios/<id>/mcp/<server>/mock.yaml`.

```yaml
name: slack                  # server name; conventionally matches the dir. Defaults to dir name.
schema: schema.json          # path to verbatim tools/list JSON (or inline `tools:` below)
handler: handler.py          # optional Python hooks; auto-detected if a handler.py sits beside this file

seed:                        # initial state, deep-copied and RESET before every run
  channels:
  - { id: C1, name: releases }
  messages: []

responses:                   # declarative dispatch, used when no handler matches the tool
  list_channels:
    result: { ok: true, channels: "{{ state.channels }}" }
  post_message:
    mutate:
    - append: { path: messages, value: { channel_name: releases, text: "{{ args.text }}" } }
    result: { ok: true, ts: "{{ now }}" }
```

You provide tools in exactly one of two ways: inline `tools:` (good for small bespoke mocks) **or** a `schema:` file reference (good for replaying a real product's schema verbatim). If both are present, inline `tools:` wins.

---

## The tool schema

Each tool is an MCP tool descriptor: `name`, `description`, `inputSchema` (JSON Schema). Inline form:

```yaml
tools:
- name: post_message
  description: Post a message to a channel by id.
  inputSchema:
    type: object
    properties:
      channel_id: { type: string }
      text: { type: string }
    required: [channel_id, text]
```

`schema.json` form — either `{"tools": [...]}` or a bare `[...]` list of the same descriptors. This is `tools/list` exactly as the real server returns it.

**Realism matters.** When emulating a real product, paste its **verbatim** schema, large `inputSchema`s and all. That bulk is the real context cost the agent pays at session start; a mock that trims it understates the difficulty of the task. The tool `name`s here are also what `capabilities.yaml` tools must reference and what `tool_called` matches.

---

## Seed state

`seed:` is an arbitrary dict that becomes the mock's mutable `state` at the start of each run. It is **deep-copied and reset before every repeat**, so runs never leak into each other. Design the seed so your assertions have concrete things to match — e.g. a channel whose `name` is `releases` so a `mock_state` jsonpath can filter on `channel_name=='releases'`, or an empty `messages: []` list that a post appends to.

The engine maintains one reserved key automatically: `__calls__`, a list of `{at, tool, args}` for every tool invocation. You never seed or touch it; `tool_called` reads from it. Don't name your own state key `__calls__`.

---

## Declarative responses

Under `responses:`, each key is a tool name mapping to one rule or a **list of rules** (tried in order, first match wins). A rule has four optional parts:

```yaml
responses:
  send_message:
  - match: { channel_id: C1 }                 # all listed args must equal (omit = match anything)
    mutate:                                     # state changes, applied in order
    - append: { path: messages, value: { text: "{{ args.text }}" } }
    result: { ok: true, ts: "{{ now }}" }       # returned to the agent (templated)
  - error: channel_not_found                    # returns { ok: false, error: "channel_not_found" }
```

- **`match`** — a dict; the rule fires only if every key equals the corresponding call arg. An empty/absent `match` matches any args. Use multiple rules to branch on arguments.
- **`mutate`** — declarative state changes (see below), applied when the rule fires.
- **`result`** — the value returned to the agent, with templating. A plain dict is auto-wrapped as MCP text content. If omitted, `{ ok: true }` is returned.
- **`error`** — shortcut that returns `{ ok: false, error: <value> }` and skips `result`.

If a tool has `responses` but **no rule matches**, the mock returns `{ ok: false, error: "no_matching_rule" }`. If a tool has **no `responses` entry at all** (and no handler), the engine returns a generic acknowledgement: `{ ok: true, note: "[<server>] mock fallback for <tool>", args: <args> }`.

---

## Templating

Result and mutation values are rendered with **Jinja2** over this context:

| variable | meaning |
|---|---|
| `args` | the tool call arguments dict |
| `state` | current mutable state dict |
| `now` | UTC ISO-8601 timestamp string |
| `uuid` | a fresh `uuid4().hex` string |

```yaml
result: { ok: true, ts: "{{ now }}", who: "{{ args.user }}", channels: "{{ state.channels }}" }
```

**Native-type rule:** if a string is *exactly one* expression like `"{{ state.channels }}"`, it resolves to the underlying Python value (list/dict/number), not its string repr — so `channels` above stays a JSON array. Mixed strings like `"posted at {{ now }}"` render to a string as usual.

---

## Mutations

Each item under `mutate:` is a single-key mapping selecting an op. `path` is a dot-path into state (intermediate keys are created as needed); values are templated.

```yaml
mutate:
- append:    { path: messages,        value: { text: "{{ args.text }}" } }   # push onto a list
- extend:    { path: messages,        value: "{{ args.batch }}" }            # concat a list onto a list
- set:       { path: meta.last_actor, value: "{{ args.user }}" }             # set/overwrite a key
- increment: { path: counters.posts,  by: 1 }                                # add to a number (default +1)
```

`append`/`extend` create the target list if missing. `set` walks/creates the dot-path. `increment` treats a missing/None value as `0`.

---

## handler.py (stateful tools)

For behavior a declarative rule can't express cleanly — reads that depend on prior writes, id/timestamp generation, search/filter/sort, validation branching — write a Python handler. Two registration styles (you can mix them):

```python
# 1) a HANDLERS dict mapping tool name -> callable
# 2) module-level functions named tool_<tool_name> (the "tool_" prefix is stripped)

def slack_send_message(args, ctx):
    state = ctx.state.data                       # the mutable state dict
    ch = next((c for c in state["channels"] if c["id"] == args.get("channel_id")), None)
    if not ch:
        return {"ok": False, "error": "channel_not_found"}      # plain dict -> auto-wrapped
    msg = {"channel_id": ch["id"], "channel_name": ch["name"], "text": args["message"]}
    ctx.state.mutate(lambda s: s["messages"].append(msg))       # in-place mutation
    return {"ok": True, "message": msg}

HANDLERS = {"slack_send_message": slack_send_message}
```

The handler contract:

- **Signature** `fn(args: dict, ctx: HandlerContext) -> dict | None`.
- **`ctx.state.data`** is the live state dict; mutate it directly or via `ctx.state.mutate(fn)`. `ctx.server` and `ctx.tool` are also available.
- **Return value**: a plain dict is auto-wrapped as MCP text content (JSON-serialized). Returning a dict that already has a `content` key is passed through untouched. Returning `None` yields `{ ok: true }`.
- A handler **overrides** any declarative `responses` rule for the same tool. The call is still recorded to `__calls__` either way.

Handlers are plain Python modules loaded fresh per server, so you can use stdlib (`time`, `uuid`, etc.) and define private helpers.

---

## Declarative vs handler: how to choose

- **Declarative** when the response is a fixed/templated value, optionally with a simple append/set, and doesn't need to read earlier mutations or compute anything. Fastest to write; keep the mock readable.
- **Handler** when the tool is stateful or computed: a `read_*` that must reflect prior `write_*` calls, generating ids/permalinks, query matching, pagination, or returning different shapes based on validation. If you find yourself writing many `match:` branches to fake logic, switch to a handler.

A common pattern is **mixed**: declarative `responses` for the trivial read-only tools, a `handler.py` for the few stateful ones.

---

## Dispatch order and built-in behavior

For each `tools/call`:

1. If the tool name isn't in the schema → JSON-RPC error `-32601 Unknown tool`.
2. If a handler is registered for it → run the handler.
3. Else if declarative `responses` exist for it → first matching rule (`match`, then `mutate`, then `error`/`result`); no match → `{ ok: false, error: "no_matching_rule" }`.
4. Else → generic fallback `{ ok: true, note: "...mock fallback...", args }`.
5. **Always** append `{at, tool, args}` to `state['__calls__']`.

The server also exposes `GET /state` (current snapshot) and `POST /__reset__` for debugging, and the framework resets state between repeats automatically — you don't call these yourself.
