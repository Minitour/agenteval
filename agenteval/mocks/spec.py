"""Parse mock.yaml into a MockSpec, plus the state container and templating.

A mock server is defined by a mock.yaml in scenarios/<id>/mcp/<server>/:

    name: slack
    schema: schema.json          # verbatim tools/list (or inline `tools:`)
    seed:                        # initial state
      channels: [...]
      messages: []
    responses:                   # declarative dispatch (optional)
      slack_send_message:
        match: { }               # optional arg matcher (all keys must equal)
        mutate:
          - append: { path: messages, value: { text: "{{ args.message }}" } }
        result: { ok: true, ts: "{{ now }}" }
    handler: handler.py          # optional Python hooks (override named tools)

Templating uses Jinja2 over { args, state, now, uuid } so declarative results
can reference call arguments and current state.
"""
from __future__ import annotations

import copy
import json
import re
import uuid as uuidlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import yaml
from jinja2 import Environment

_JINJA = Environment(autoescape=False)

# A string that is exactly one Jinja expression, e.g. "{{ state.channels }}".
# These resolve to the native Python value rather than its string repr.
_SOLE_EXPR = re.compile(r"^\s*\{\{(?P<expr>.+?)\}\}\s*$", re.DOTALL)


# ── State ────────────────────────────────────────────────────────────────────


class MockState:
    """Mutable in-memory state seeded from mock.yaml `seed`.

    Mirrors the contract of the original Node mock so handler functions port
    over with minimal changes: `state.data` is the dict, `state.mutate(fn)`
    applies an in-place mutation.
    """

    def __init__(self, seed: dict[str, Any] | None = None):
        self._seed = copy.deepcopy(seed or {})
        self.data: dict[str, Any] = copy.deepcopy(self._seed)

    def mutate(self, fn: Callable[[dict[str, Any]], None]) -> None:
        fn(self.data)

    def reset(self) -> None:
        self.data = copy.deepcopy(self._seed)

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.data)


# ── Spec ─────────────────────────────────────────────────────────────────────


@dataclass
class ResponseRule:
    match: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    mutate: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def matches(self, args: dict[str, Any]) -> bool:
        return all(args.get(k) == v for k, v in self.match.items())


@dataclass
class MockSpec:
    name: str
    dir: Path
    tools: list[dict[str, Any]] = field(default_factory=list)
    seed: dict[str, Any] = field(default_factory=dict)
    responses: dict[str, list[ResponseRule]] = field(default_factory=dict)
    handler_path: Optional[Path] = None

    def tool_names(self) -> set[str]:
        return {t.get("name", "") for t in self.tools}


def _load_tools(raw: dict[str, Any], mock_dir: Path) -> list[dict[str, Any]]:
    if "tools" in raw and raw["tools"]:
        return list(raw["tools"])
    schema_ref = raw.get("schema")
    if not schema_ref:
        return []
    schema_path = (mock_dir / schema_ref).resolve()
    if not schema_path.exists():
        raise FileNotFoundError(f"mock '{raw.get('name')}' schema not found: {schema_path}")
    doc = json.loads(schema_path.read_text())
    # schema.json may be {"tools": [...]} or a bare list
    if isinstance(doc, dict):
        return list(doc.get("tools", []))
    return list(doc)


def _parse_rules(raw_responses: dict[str, Any]) -> dict[str, list[ResponseRule]]:
    out: dict[str, list[ResponseRule]] = {}
    for tool, spec in (raw_responses or {}).items():
        items = spec if isinstance(spec, list) else [spec]
        rules: list[ResponseRule] = []
        for item in items:
            item = item or {}
            rules.append(
                ResponseRule(
                    match=item.get("match", {}) or {},
                    result=item.get("result"),
                    mutate=item.get("mutate", []) or [],
                    error=item.get("error"),
                )
            )
        out[tool] = rules
    return out


def load_mock_spec(mock_dir: Path) -> MockSpec:
    mock_dir = mock_dir.resolve()
    spec_path = mock_dir / "mock.yaml"
    if not spec_path.exists():
        raise FileNotFoundError(f"no mock.yaml in {mock_dir}")
    raw = yaml.safe_load(spec_path.read_text()) or {}
    name = raw.get("name", mock_dir.name)

    handler_ref = raw.get("handler")
    handler_path: Optional[Path] = None
    if handler_ref:
        handler_path = (mock_dir / handler_ref).resolve()
    elif (mock_dir / "handler.py").exists():
        handler_path = (mock_dir / "handler.py").resolve()

    return MockSpec(
        name=name,
        dir=mock_dir,
        tools=_load_tools(raw, mock_dir),
        seed=raw.get("seed", {}) or {},
        responses=_parse_rules(raw.get("responses", {})),
        handler_path=handler_path,
    )


# ── Templating + declarative mutation ────────────────────────────────────────


def _render_scalar(value: str, ctx: dict[str, Any]) -> Any:
    # If the whole string is a single expression, return the native value
    # (list/dict/number) so results keep their JSON types.
    sole = _SOLE_EXPR.match(value)
    if sole:
        compiled = _JINJA.compile_expression(sole.group("expr").strip(), undefined_to_none=True)
        return compiled(**ctx)
    return _JINJA.from_string(value).render(**ctx)


def render_value(value: Any, ctx: dict[str, Any]) -> Any:
    """Recursively render Jinja2 templates inside strings of a result object."""
    if isinstance(value, str):
        return _render_scalar(value, ctx)
    if isinstance(value, dict):
        return {k: render_value(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, ctx) for v in value]
    return value


def template_context(args: dict[str, Any], state: MockState) -> dict[str, Any]:
    return {
        "args": args,
        "state": state.data,
        "now": datetime.now(timezone.utc).isoformat(),
        "uuid": uuidlib.uuid4().hex,
    }


def _resolve_path(data: dict[str, Any], path: str, create: bool = False) -> tuple[Any, str]:
    """Walk a dot-path, returning (parent_container, last_key)."""
    parts = path.split(".")
    cur: Any = data
    for key in parts[:-1]:
        if key not in cur or not isinstance(cur[key], (dict, list)):
            if create:
                cur[key] = {}
            else:
                raise KeyError(path)
        cur = cur[key]
    return cur, parts[-1]


def apply_mutations(mutations: list[dict[str, Any]], state: MockState, ctx: dict[str, Any]) -> None:
    """Apply declarative mutations to state in order.

    Supported ops (each mutation is a single-key mapping):
      - append:    { path: <dotpath to list>, value: <templated> }
      - extend:    { path: <dotpath to list>, value: <templated list> }
      - set:       { path: <dotpath>, value: <templated> }
      - increment: { path: <dotpath to number>, by: <int, default 1> }
    """
    for mutation in mutations:
        for op, body in mutation.items():
            body = body or {}
            path = body.get("path")
            if not path:
                continue

            def do(data: dict[str, Any], op=op, body=body, path=path) -> None:
                if op == "append":
                    parent, key = _resolve_path(data, path, create=True)
                    parent.setdefault(key, [])
                    parent[key].append(render_value(body.get("value"), ctx))
                elif op == "extend":
                    parent, key = _resolve_path(data, path, create=True)
                    parent.setdefault(key, [])
                    parent[key].extend(render_value(body.get("value", []), ctx))
                elif op == "set":
                    parent, key = _resolve_path(data, path, create=True)
                    parent[key] = render_value(body.get("value"), ctx)
                elif op == "increment":
                    parent, key = _resolve_path(data, path, create=True)
                    parent[key] = (parent.get(key, 0) or 0) + int(body.get("by", 1))

            state.mutate(do)
