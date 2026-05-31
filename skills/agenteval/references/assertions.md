# Assertions

Assertions are the deterministic, mechanical checks that make an agent run pass or fail. They are listed under `assertions:` in `scenario.yaml`. Each is a mapping with a `kind` (selecting the check), an optional `name` (a label shown in reports; defaults to the kind), an optional `required` (default `true`), and kind-specific parameters.

A **required** failure fails the run and the suite (nonzero exit, gating CI). Mark a check `required: false` to surface it in reports without gating — useful for "nice to have" behaviors you're tracking but not enforcing yet.

Design guidance: prefer assertions that check **what the agent did to the world** (`mock_state`, `tool_called`, file checks) over what it *said* (`output_*`). Models routinely narrate actions they never performed; side-effect checks are what give agenteval real red/green.

## Quick reference

| kind | params | checks |
|---|---|---|
| `mock_state` | `server`, `jsonpath`, `min_count`, `max_count` | JSONPath match count against a mock's final state |
| `tool_called` | `tool`, `server`, `min_count`, `max_count` | a tool was (or never was) invoked |
| `file_exists` | `path` | a file exists in the workspace |
| `file_contains` | `path`, `values`, `mode` | file contains all/any of `values` |
| `dir_has_new_file` | `path`, `matches`, `contents_include` | a matching file with given contents exists |
| `output_contains` | `values`, `mode`, `ignore_case` | final answer contains all/any of `values` |
| `output_matches` | `pattern`, `ignore_case` | final answer matches a regex |

---

## mock_state

Match a JSONPath against a mock server's **final** state (after the run), and assert the number of matches.

```yaml
- kind: mock_state
  name: posted-to-releases
  server: slack                  # required; the mock whose state to inspect
  jsonpath: "$.messages[?(@.channel_name=='releases')]"   # required
  min_count: 1                   # default 1
  max_count: 3                   # optional upper bound
```

Supported JSONPath forms:

- **Plain path** — `$.messages`, `$.team.name`. Resolves the dotted path; a list yields its elements as matches, a scalar yields a single match, missing yields zero.
- **Goessner equality filter** — `$.coll[?(@.field=='value')]`. Filters a list to items where `field == value` (string comparison). `field` may itself be dotted (`@.profile.team`).
- **Anything else** falls back to `jsonpath-ng` (extended) — full JSONPath for richer queries.

This is your strongest determinism check: it proves the world actually changed the way the task required (a message landed, a record was created, a counter incremented). Use `max_count` to also assert the agent didn't *over*-act (e.g. posted exactly once, not three times).

---

## tool_called

Assert a tool was invoked a certain number of times. Reads the auto-recorded call log (`__calls__`).

```yaml
- kind: tool_called
  name: called-send-message
  tool: slack_send_message       # required
  server: slack                  # optional; restrict to one mock server
  min_count: 1                   # default 1 (see nuance below)
  max_count: 1                   # optional upper bound
```

**Default-min nuance:** `min_count` defaults to `1`, *unless* you specify `max_count` and omit `min_count`, in which case the default min drops to `0`. This makes the "never called" idiom clean:

```yaml
- kind: tool_called              # prove a dangerous tool was NEVER called
  name: never-deleted-users
  tool: delete_user
  max_count: 0                   # min defaults to 0, so 0 calls passes; 1+ fails
```

Pair `tool_called` with `mock_state`: `tool_called` proves the agent *invoked* the tool; `mock_state` proves the invocation had the right *effect*. Together they catch both "claimed but never called" and "called but with wrong args."

---

## file_exists

A path exists in the ephemeral workspace (relative to the workspace root, where the scenario's `assets/` were copied and where the agent works).

```yaml
- kind: file_exists
  path: docs/CHANGELOG.md        # required
```

---

## file_contains

A file exists and contains the given substrings.

```yaml
- kind: file_contains
  path: docs/CHANGELOG.md        # required
  values: ["1.2.0", "Alembic"]   # required; list of substrings
  mode: all                      # "all" (default) = every value present; "any" = at least one
```

Plain substring matching (not regex). Reports which values were found vs. missing. A missing file fails the assertion.

---

## dir_has_new_file

A directory contains a file matching a glob, optionally with required contents. Useful when you don't know the exact filename the agent will choose.

```yaml
- kind: dir_has_new_file
  path: reports                  # required; directory (relative to workspace)
  matches: "*.md"                # glob (default "*")
  contents_include: ["summary"]  # optional; a single matching file must contain ALL of these
```

Passes if at least one file matches the glob; if `contents_include` is given, at least one matching file must contain every listed substring.

---

## output_contains

The agent's **final textual answer** contains the given substrings.

```yaml
- kind: output_contains
  values: ["message_link", "posted"]   # required
  mode: any                            # "all" (default) or "any"
  ignore_case: true                    # default false
```

Use sparingly — the final answer is free-form prose and brittle to assert on. Prefer it for confirming the agent surfaced a specific artifact to the user (a permalink, an id) rather than for verifying behavior.

---

## output_matches

The final answer matches a regular expression (Python `re.search`, so it matches anywhere).

```yaml
- kind: output_matches
  pattern: "https://[\\w.-]+\\.slack\\.com/archives/\\S+"   # required
  ignore_case: false                                        # default false
```

Good for asserting the output contains a well-formed link/id pattern. Remember YAML string escaping: backslashes in the regex need escaping (or use a single-quoted YAML scalar).

---

## Picking assertions for a scenario

A solid scenario usually combines:

1. One or more `tool_called` — the agent actually used the tools (and didn't touch forbidden ones, via `max_count: 0`).
2. One or more `mock_state` — those calls produced the correct side effects in state.
3. Optional `file_*` — if the task writes to the workspace.
4. Optional `output_*` — only if a specific string/link must appear in the final answer.
5. A `judge` rubric (not an assertion) for subjective quality.

Keep each assertion checking one thing, give it a descriptive `name`, and let the suite's nonzero exit gate your CI.
