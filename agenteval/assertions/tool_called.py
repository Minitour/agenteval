"""tool_called assertion: verify a tool was (or was not) invoked.

Params:
  tool       tool name (required)
  server     optional mock server filter
  min_count  minimum invocations (default 1)
  max_count  optional maximum invocations (use 0 to assert it was never called)
"""
from __future__ import annotations

from .base import AssertContext, Assertion


class ToolCalledAssertion(Assertion):
    kind = "tool_called"

    def evaluate(self, ctx: AssertContext) -> tuple[bool, str]:
        tool = self._require("tool")
        server = self.params.get("server")
        max_count = self.params.get("max_count")
        # Default min_count is 1, but drops to 0 when only a max is specified
        # so `max_count: 0` cleanly expresses "this tool was never called".
        default_min = 0 if max_count is not None else 1
        min_count = int(self.params.get("min_count", default_min))

        calls = [
            c
            for c in ctx.tool_calls
            if c.get("tool") == tool and (server is None or c.get("server") == server)
        ]
        n = len(calls)
        where = f" on '{server}'" if server else ""
        if n < min_count:
            return False, f"'{tool}'{where} called {n}x, need >= {min_count}"
        if max_count is not None and n > int(max_count):
            return False, f"'{tool}'{where} called {n}x, need <= {max_count}"
        return True, f"'{tool}'{where} called {n}x"
