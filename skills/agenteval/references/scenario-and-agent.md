# Scenario, agent, and project config

Exact, verified fields for `scenario.yaml`, `capabilities.yaml`, `agenteval.yaml`, and the judge/rubric. Anything not listed here is not parsed.

## Table of contents

- [scenario.yaml](#scenarioyaml)
- [The judge and rubric](#the-judge-and-rubric)
- [Assets and the ephemeral workspace](#assets-and-the-ephemeral-workspace)
- [capabilities.yaml (the agent)](#capabilitiesyaml-the-agent)
- [agenteval.yaml (project config)](#agentevalyaml-project-config)

---

## scenario.yaml

Lives at `scenarios/<id>/scenario.yaml`. One scenario = one test case.

```yaml
id: slack-release-note            # optional; defaults to the directory name
description: Post a release note.  # optional; shown in `agenteval list`
agent: release-bot                 # REQUIRED; must match a dir under agents/
prompt_file: input/prompt.md       # path to the task prompt (default: input/prompt.md)
# prompt: "do the thing inline"    # inline alternative; if present it WINS over prompt_file
mcp: [slack]                       # which mocks to start (dir names under mcp/)
assets: assets                     # optional; dir copied into the workspace (default: ./assets if present)

run:                               # all optional; fall back to agenteval.yaml then built-in defaults
  models: [claude-opus-4-8]        # per-scenario model override
  repeats: 1                       # how many times to run each (scenario, model) cell
  timeout_seconds: 300
  max_turns: 15

assertions:                        # list; see references/assertions.md
- kind: mock_state
  name: posted-to-releases         # optional label shown in reports (defaults to kind)
  server: slack
  jsonpath: "$.messages[?(@.channel_name=='releases')]"
  min_count: 1
- kind: tool_called
  name: discovered-channel
  server: slack
  tool: slack_search_channels
  min_count: 1
  required: false                  # reports but does not gate the run

judge:                             # optional; omit if you only use assertions
  rubric_file: rubric.md
  min_score: 0.6
```

### Field rules

- **Prompt resolution**: inline `prompt:` takes precedence; otherwise `prompt_file:` is read (defaulting to `input/prompt.md`). A missing prompt file is a hard error.
- **`agent`** is required and must resolve to `agents/<agent>/capabilities.yaml`, or `validate` fails.
- **`mcp`** entries each require a matching `mcp/<name>/mock.yaml` in the scenario dir.
- A scenario with **neither assertions nor a judge** is invalid — there'd be nothing to check.
- Every assertion needs a `kind`. `name` and `required` (default `true`) are handled specially; all other keys are passed to the assertion as parameters.

---

## The judge and rubric

The LLM-as-judge scores the agent's final output against a rubric, producing a score in `0..1`. Configure it per scenario under `judge:`:

```yaml
judge:
  enabled: true                    # default true
  rubric_file: rubric.md           # path relative to the scenario dir
  # rubric: "inline rubric text"   # inline alternative to rubric_file
  model: claude-opus-4-8           # defaults to agenteval.yaml judge.model
  min_score: 0.6                   # run fails if score < this (default from config, else 0.0)
  required: true                   # default true; a failing required judge fails the run
```

You must provide **either** `rubric_file` **or** `rubric` — a judge with neither is invalid. The judge backend is set globally in `agenteval.yaml` (`judge.backend`), defaulting to `claude-cli` (reuses the Claude Code CLI auth, so no `ANTHROPIC_API_KEY` needed); set it to `anthropic-api` to use the Anthropic SDK with `ANTHROPIC_API_KEY`. Skip the judge for a whole run with `agenteval run --no-judge`.

### Rubric structure

A rubric is plain markdown the judge reads. The convention that scores reliably: list concrete **anchors** (binary, checkable claims) and a **scoring scale** mapping how many anchors are hit to a `0..1` score. Keep the determinism-critical requirements in assertions; the rubric judges what's left (quality, tone, completeness).

```markdown
# Rubric: slack-release-note

## Anchors
1. Channel — message targets #releases (channel_id C09RELEASE01).
2. Brevity — body is at most 4 sentences.
3. Backend mention — references the FastAPI backend or version 1.2.0.
4. Feature coverage — touches at least two of: SQLModel users+items, JWT login, Alembic, FastAPI.
5. Tone — short, professional, no marketing fluff.

## Scoring (return a score in 0..1)
- 1.0: all anchors; reads like a real release note.
- 0.8: all anchors with a minor issue (e.g. 5 sentences).
- 0.6: 3 anchors hit.
- 0.4: wrong channel or off-topic; or only 2 anchors.
- 0.2 or below: did not actually post, or posted nonsense.
```

---

## Assets and the ephemeral workspace

Each `(scenario, model, repeat)` run gets a **fresh** workspace directory (under `<project>/.agenteval-runtime/`) that is deleted afterward unless you pass `--keep-workspace`. If the scenario has an `assets/` dir (or a custom `assets:` path), its **contents** (not the dir itself) are copied into the workspace root before the agent runs. This is how you give the agent a repo/files to operate on, and how filesystem assertions (`file_exists`, `file_contains`, `dir_has_new_file`) have something to check — those assertions are evaluated against this workspace.

---

## capabilities.yaml (the agent)

This is a [capa](https://github.com/infragate/capa) spec. agenteval compiles it per run: it keeps only the `servers` whose `id` matches a started mock, **rewrites those servers' `url` to the local mock endpoint**, prunes `tools` whose server isn't live, prunes skill `requires` to surviving tools, and resolves local `path`s to absolute. So the `url` you write is a throwaway placeholder.

```yaml
providers:
- claude-code                      # target harness(es) capa compiles for

options:
  toolExposure: expose-all         # how tools are surfaced to the agent

agents:
  base:
    type: local
    path: ./CLAUDE.md              # base/system prompt for the agent (resolved to absolute)

skills:                            # optional local agent skills
- id: slack
  type: local
  def:
    path: ./skills/slack           # dir containing SKILL.md
    requires:                      # tool refs this skill needs; pruned to live tools
    - '@slack.slack_send_message'
    - '@slack.slack_search_channels'
  description: Compose, search, and post to Slack.

servers:                           # MCP servers the agent can reach
- id: slack                        # MUST match the mock dir/name and scenario mcp: entry
  type: mcp
  def:
    url: http://127.0.0.1:0/mcp    # placeholder; rewritten to the live mock at run time
  description: Slack mock backend

tools:                             # individual tools the agent may call
- id: slack_send_message
  type: mcp
  def:
    server: '@slack'               # '@' + server id
    tool: slack_send_message       # MUST exist in the slack mock's schema
- id: slack_search_channels
  type: mcp
  def:
    server: '@slack'
    tool: slack_search_channels
```

Key invariant: a tool's `def.tool` must be a tool name present in that server's mock schema (`tools:` or `schema.json`). Because mocks boot before `capa install`, capa validates the agent against the live mock and a mismatch fails install.

---

## agenteval.yaml (project config)

Project-wide defaults; scenarios can override `run.*`, and the CLI overrides everything.

```yaml
provider: claude                   # provider name (default "claude"); --provider overrides

models: [claude-opus-4-8]          # default models; passed to `claude --model`; --model overrides
repeats: 1                         # default repeats per (scenario, model); --repeat overrides
timeout_seconds: 300               # per-run wall clock
max_turns: 25                      # default cap on agent turns

judge:
  enabled: true
  model: claude-opus-4-8
  min_score: 0.0                   # default gate when a scenario doesn't set its own
  backend: claude-cli              # or "anthropic-api" (uses ANTHROPIC_API_KEY)
  cli: claude

report:
  dir: reports                     # relative to project root unless absolute

providers:                         # optional provider-specific overrides
  claude:
    cli: claude                    # provider CLI binary name
    capa_bin: capa                 # capa binary name
```

### Reports written by `agenteval run`

Into `report.dir` (default `reports/`):

- `results.json` — full per-run records plus per-cell aggregates (mean/stddev/median/min/max per metric, pass rate, judge score).
- `junit.xml` — one testcase per repeat, for native CI gating.
- `report.md` — a results table plus a failure breakdown, good for PR comments.

The process exits nonzero if any run failed, which is what gates a PR/MR in CI.
