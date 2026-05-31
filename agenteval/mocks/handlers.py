"""Load optional Python handler hooks for a mock server.

A handler.py module may expose tool handlers in either form:

  1. A module-level ``HANDLERS`` dict mapping tool name -> callable.
  2. Functions named ``tool_<tool_name>`` (the ``tool_`` prefix is stripped).

Each handler has the signature ``handler(args: dict, ctx: HandlerContext) ->
dict | None`` and may mutate ``ctx.state.data`` in place or via
``ctx.state.mutate(fn)``. Returning a plain dict is auto-wrapped as MCP text
content by the engine; returning a dict that already has a ``content`` key is
passed through untouched.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .spec import MockState

Handler = Callable[[dict[str, Any], "HandlerContext"], Optional[dict[str, Any]]]


@dataclass
class HandlerContext:
    state: MockState
    server: str
    tool: str


def load_handlers(handler_path: Optional[Path], server_name: str) -> dict[str, Handler]:
    if not handler_path or not handler_path.exists():
        return {}

    mod_name = f"agenteval_mock_handler_{server_name}_{abs(hash(str(handler_path)))}"
    spec = importlib.util.spec_from_file_location(mod_name, handler_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load handler module at {handler_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    handlers: dict[str, Handler] = {}

    registered = getattr(module, "HANDLERS", None)
    if isinstance(registered, dict):
        handlers.update(registered)

    for attr in dir(module):
        if attr.startswith("tool_"):
            fn = getattr(module, attr)
            if callable(fn):
                handlers[attr[len("tool_") :]] = fn

    return handlers
