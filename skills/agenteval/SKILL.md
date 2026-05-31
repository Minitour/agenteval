---
name: agenteval
description: >-
  Author end-to-end agenteval evals — unit tests for AI agents. Scaffold the project, declare the
  agent via capa's capabilities.yaml, stand up mock MCP servers (mock.yaml + handler.py + schema),
  seed deterministic state, write assertions (mock_state, tool_called, file/output checks) and an
  optional LLM-judge rubric, then validate and run the suite. Use this skill whenever someone is
  working with agenteval / the agenteval-framework PyPI package: creating or editing scenario.yaml,
  mock.yaml, capabilities.yaml, agenteval.yaml, or rubric files; mocking an MCP server for agent
  testing; adding or debugging assertions; or wiring `agenteval init/validate/run` into CI. Trigger
  even when the user only says "write a test/eval/scenario for my agent", "mock this MCP server so I
  can test the agent", "assert the agent posted to Slack", or "gate my agent in CI" — if the context
  is agenteval, reach for this skill rather than improvising the file formats from memory.
---

# Authoring agenteval evals

`agenteval` treats one agent run like one unit test. You declare an agent once (with [capa](https://github.com/infragate/capa)'s `capabilities.yaml`), then write **scenarios** next to it: a prompt, a set of **mock MCP servers** seeded with state you control, and **assertions** about what should happen. One command runs the whole `(scenario × model × repeat)` matrix in throwaway workspaces that talk only to local mocks, checks the side effects, and exits nonzero when something regresses (JUnit XML drops straight into CI).

The reason the framework exists: real agent tests call live SaaS APIs, burn tokens, and answer differently every run, so most "tests" are a human eyeballing output once. agenteval gives you red/green by (a) replacing real services with deterministic local mocks that **record every tool call**, and (b) asserting on **side effects** (state changed, tool invoked, file written) rather than on what the model *claims* it did. Keep that principle front of mind: the most valuable assertions check what the agent *did*, and the LLM judge is reserved for genuinely subjective quality.

## Prerequisites and commands

The user's project needs three things on PATH before a run will work — surface any that are missing rather than letting a run fail cryptically:

- `pip install agenteval-framework` (the import package and CLI are both `agenteval`).
- The `capa` binary — agenteval shells out to `capa install -p claude-code` to compile `capabilities.yaml`.
- The provider CLI — for the default `claude` provider that's the `claude` CLI (Claude Code), authenticated by subscription or `ANTHROPIC_API_KEY` (in the env or a project-root `.env`).

```
agenteval init [TARGET]   scaffold a runnable project (agent + one scenario + mock)
agenteval validate        structural check, NO model calls — run this first, always
agenteval list            list discovered scenarios
agenteval run -v          run the suite, emit reports, exit nonzero on failure
```

`run` flags worth knowing: `--root`, `--filter <substr>` (run a subset by id), `--model <m>` (repeatable, overrides config), `--repeat N`, `--no-judge` (skip the judge to save tokens while iterating on determinism), `--keep-workspace` (keep the ephemeral dir to inspect file side effects), `--report-dir`.

`agenteval validate` is your fast feedback loop. It catches the most common authoring mistakes (missing `capabilities.yaml`, a `mcp:` entry with no `mock.yaml`, a scenario with nothing to check, a judge with no rubric) **without spending a single token**. Run it after every structural edit.

## Project layout

A project is a directory with `agenteval.yaml`, an `agents/` folder, and a `scenarios/` folder. The names in bold below are load-bearing — they must line up or `validate` fails (see "How the names connect").

```
my-eval/
  agenteval.yaml                  # provider, models, repeats, judge, report config
  .env                            # ANTHROPIC_API_KEY etc. (user brings; never committed)
  agents/
    <agent-name>/
      capabilities.yaml           # capa spec -> provider config (REQUIRED per agent)
      CLAUDE.md                   # base prompt, referenced from capabilities.yaml (optional)
      skills/<skill>/SKILL.md     # local agent skills (optional)
  scenarios/
    <scenario-id>/
      scenario.yaml               # agent ref, prompt, mcp list, assertions, judge (REQUIRED)
      input/prompt.md             # the task prompt (default location)
      rubric.md                   # LLM-judge rubric (optional)
      assets/                     # files copied into the ephemeral workspace (optional)
      mcp/
        <server>/
          mock.yaml               # seed state + declarative responses + schema/handler refs
          schema.json             # verbatim tools/list (optional; can inline under `tools:`)
          handler.py              # optional Python hooks for stateful tools
  reports/                        # output: results.json, junit.xml, report.md (gitignored)
```

## The authoring workflow

Work in this order — each step depends on the previous one, and doing them out of order is the usual cause of confusing `validate` errors.

1. **Scaffold or locate the project.** For a new project, run `agenteval init <dir>`; it writes a complete, runnable example (one agent, one scenario, one declarative mock) that is the best possible starting template — read it, then adapt rather than inventing structure. For an existing project, find the `agents/` and `scenarios/` dirs.

2. **Define the agent** under `agents/<name>/capabilities.yaml`. This is a capa spec listing the providers, the MCP `servers` the agent can reach, the `tools` it may call, an optional base prompt (`agents.base.path` → e.g. `CLAUDE.md`), and optional local `skills`. At run time agenteval **rewrites each server's `url` to the local mock**, so the URL in the file is just a placeholder (`http://127.0.0.1:0/mcp` is conventional). See `references/scenario-and-agent.md`.

3. **Build a mock for every external dependency** the agent touches, under `scenarios/<id>/mcp/<server>/mock.yaml`. Decide per tool: a **declarative** `responses:` rule for simple deterministic returns, or a **`handler.py`** function for stateful behavior (reads that depend on prior writes, id generation, search/filtering). Seed the initial `state` so assertions have something concrete to match. See `references/mocks.md`.

4. **Write `scenario.yaml`**: point `agent:` at the agent dir, give it a `prompt` (inline) or `prompt_file:` (default `input/prompt.md`), list which mocks to start under `mcp:`, then add `assertions:` and an optional `judge:`. See `references/scenario-and-agent.md`.

5. **Write assertions that check side effects.** Prefer `mock_state` (did the world change the way it should?) and `tool_called` (did the agent actually invoke the tool, including `max_count: 0` to prove it *never* called a dangerous tool?) over output text checks. Use `file_*` / `dir_has_new_file` for filesystem side effects, `output_*` sparingly for the final answer. See `references/assertions.md` for all seven kinds.

6. **Add a judge rubric only for subjective quality** (tone, brevity, "reads like a real release note"). Put hard, deterministic requirements in assertions instead — the judge is non-deterministic and should never be the only thing gating a behavior you can check mechanically.

7. **`agenteval validate`, fix problems, then `agenteval run -v`.** Iterate on determinism first with `--no-judge`, add the judge once behavior is solid.

## How the names connect (the #1 source of errors)

Four names must agree across files. When `validate` complains or a tool "isn't found", check this chain first:

- The **mock directory name** (`mcp/<server>/`) and the `name:` inside its `mock.yaml`.
- The scenario's `mcp: [<server>]` list — each entry must have a matching `mcp/<server>/mock.yaml`.
- The `servers: [{ id: <server> }]` in `capabilities.yaml` — agenteval keeps only servers whose `id` matches a started mock and rewrites their URL; servers with no mock are pruned.
- The `tools:` in `capabilities.yaml` reference `def: { server: '@<server>', tool: <tool> }`, and `<tool>` **must be a tool name present in the mock's schema** (`tools:` or `schema.json`). Mocks start *before* `capa install`, so capa validates the agent's tools against the live mock — a typo'd tool name surfaces here.

Mnemonic: `mcp/slack/` → `name: slack` → `mcp: [slack]` → `servers: [{id: slack}]` → `tool: slack_send_message` exists in slack's schema.

## Worked minimal example

A scenario asserting the agent discovers a channel and posts to it. The mock is fully declarative (no Python needed):

`scenarios/post-note/scenario.yaml`
```yaml
id: post-note
description: Agent posts a release note to #releases.
agent: release-bot
prompt_file: input/prompt.md
mcp: [demo]
run:
  repeats: 1
  max_turns: 15
assertions:
- kind: tool_called          # it actually posted, not just claimed to
  name: called-post
  server: demo
  tool: post_message
  min_count: 1
- kind: mock_state           # a message really landed in #releases
  name: landed-in-releases
  server: demo
  jsonpath: "$.messages[?(@.channel_name=='releases')]"
  min_count: 1
judge:
  rubric_file: rubric.md     # quality only; determinism is the assertions' job
  min_score: 0.6
```

`scenarios/post-note/mcp/demo/mock.yaml`
```yaml
name: demo
seed:
  channels:
  - { id: C1, name: releases }
  messages: []
tools:
- name: list_channels
  description: List channels in the workspace.
  inputSchema: { type: object, properties: {} }
- name: post_message
  description: Post a message to a channel by id.
  inputSchema:
    type: object
    properties:
      channel_id: { type: string }
      text: { type: string }
    required: [channel_id, text]
responses:
  list_channels:
    result: { ok: true, channels: "{{ state.channels }}" }
  post_message:
    mutate:
    - append:
        path: messages
        value: { channel_id: "{{ args.channel_id }}", channel_name: releases, text: "{{ args.text }}" }
    result: { ok: true, ts: "{{ now }}" }
```

This is the shape of a good eval: the prompt asks for a real action, the mock records it deterministically, two assertions prove the side effect, and the judge only weighs in on prose quality.

## Common pitfalls

- **Asserting on the final answer instead of the world.** "The output says it posted" is not the same as "a message is in `state.messages`." Models narrate actions they didn't take; assert side effects.
- **Forgetting the engine records calls automatically.** Every `tools/call` is appended to the mock's `state['__calls__']`, which is what `tool_called` reads — you do not seed or maintain `__calls__` yourself.
- **Declarative when you needed stateful.** A read tool that must reflect a prior write (e.g. `read_channel` after `post_message`) needs a `handler.py`; a single declarative `result:` can't see earlier mutations cleanly. Reach for `references/mocks.md`.
- **Schema realism.** When mocking a real product, replay its **verbatim** tool schema (large `inputSchema`s and all). That bulk is exactly the context cost a real agent pays, so a realistic eval must include it.
- **Judge doing the assertions' job.** If a requirement is checkable (right channel, tool called, file exists), encode it as an assertion. Reserve `min_score` gating for taste.
- **`required: false` semantics.** Assertions are `required: true` by default; a required failure fails the run and the suite (nonzero exit). Mark exploratory checks `required: false` so they report without gating.

## Reference files

Read the relevant one before writing that file type — these contain the exact, verified field names and semantics:

- `references/scenario-and-agent.md` — every field of `scenario.yaml`, `capabilities.yaml`, `agenteval.yaml`, plus judge/rubric and assets.
- `references/mocks.md` — `mock.yaml` (declarative `responses`, `mutate` ops, Jinja2 templating), `handler.py` contract, and schema handling.
- `references/assertions.md` — all seven assertion kinds with parameters, defaults, and the subtle bits (e.g. `tool_called` with `max_count: 0`, `mock_state` jsonpath forms).
