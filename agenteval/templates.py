"""Project scaffolding used by `agenteval init`.

Writes a minimal but runnable eval project: one agent (capabilities.yaml), one
scenario with a declarative mock, an assertion, and a judge rubric.
"""
from __future__ import annotations

from pathlib import Path

_AGENTEVAL_YAML = """\
# agenteval project config
provider: claude
models: [claude-opus-4-8]
repeats: 1
timeout_seconds: 300

judge:
  enabled: true
  model: claude-opus-4-8
  min_score: 0.6

report:
  dir: reports
"""

_ENV_EXAMPLE = """\
# Copy to .env and fill in. The framework never writes keys to disk.
ANTHROPIC_API_KEY=
"""

_CAPABILITIES_YAML = """\
# capa capabilities for this agent. `agenteval` rewrites server URLs to the
# local mocks at run time, so the url below is just a placeholder.
providers:
- claude-code
options:
  toolExposure: expose-all
servers:
- id: demo
  type: mcp
  def:
    url: http://127.0.0.1:0/mcp
  description: Demo mock backend
tools:
- id: post_message
  type: mcp
  def:
    server: '@demo'
    tool: post_message
- id: list_channels
  type: mcp
  def:
    server: '@demo'
    tool: list_channels
"""

_SCENARIO_YAML = """\
id: example
description: Agent posts a message to the releases channel.
agent: agent_1
prompt_file: input/prompt.md
mcp: [demo]
run:
  repeats: 1
assertions:
- kind: tool_called
  server: demo
  tool: post_message
  min_count: 1
- kind: mock_state
  server: demo
  jsonpath: "$.messages[?(@.channel_name=='releases')]"
  min_count: 1
judge:
  rubric_file: rubric.md
  min_score: 0.6
"""

_PROMPT_MD = """\
Find the channel named "releases" using list_channels, then post a short, \
friendly message to it announcing that version 1.0 shipped. Use the demo \
tools available to you to actually post.
"""

_RUBRIC_MD = """\
# Rubric

Award a high score when:
1. The message was posted to the `releases` channel.
2. The message mentions version 1.0.
3. The tone is short and friendly.
"""

_MOCK_YAML = """\
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
"""

_FILES = {
    "agenteval.yaml": _AGENTEVAL_YAML,
    ".env.example": _ENV_EXAMPLE,
    "agents/agent_1/capabilities.yaml": _CAPABILITIES_YAML,
    "scenarios/example/scenario.yaml": _SCENARIO_YAML,
    "scenarios/example/input/prompt.md": _PROMPT_MD,
    "scenarios/example/rubric.md": _RUBRIC_MD,
    "scenarios/example/mcp/demo/mock.yaml": _MOCK_YAML,
}


def scaffold_project(target: Path) -> list[str]:
    target = Path(target)
    created: list[str] = []
    for rel, content in _FILES.items():
        path = target / rel
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        created.append(rel)
    return created
