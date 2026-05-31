"""mock_state assertion: match a JSONPath against a mock server's final state.

Params:
  server     mock server name (required)
  jsonpath   JSONPath expression (required)
  min_count  minimum number of matches (default 1)
  max_count  optional maximum number of matches

Supports the Goessner filter form used by the benchmark
(`$.messages[?(@.channel_name=='releases')]`) and plain paths (`$.messages`)
natively, and falls back to jsonpath-ng (extended) for anything else.
"""
from __future__ import annotations

import re
from typing import Any

from .base import AssertContext, Assertion

_FILTER_RE = re.compile(
    r"^\$\.(?P<coll>[\w.]+)\[\?\(@\.(?P<field>[\w.]+)\s*==\s*(?P<q>['\"])(?P<val>.*?)(?P=q)\)\]$"
)
_PLAIN_RE = re.compile(r"^\$\.(?P<path>[\w.]+)$")


def _dig(data: Any, dotted: str) -> Any:
    cur = data
    for key in dotted.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


def _matches(state: dict[str, Any], jsonpath: str) -> list[Any]:
    m = _FILTER_RE.match(jsonpath)
    if m:
        coll = _dig(state, m.group("coll")) or []
        field, val = m.group("field"), m.group("val")
        return [item for item in coll if isinstance(item, dict) and str(_dig(item, field)) == val]

    m = _PLAIN_RE.match(jsonpath)
    if m:
        value = _dig(state, m.group("path"))
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    # Fallback: jsonpath-ng extended for richer expressions.
    from jsonpath_ng.ext import parse as parse_ext

    return [match.value for match in parse_ext(jsonpath).find(state)]


class MockStateAssertion(Assertion):
    kind = "mock_state"

    def evaluate(self, ctx: AssertContext) -> tuple[bool, str]:
        server = self._require("server")
        jsonpath = self._require("jsonpath")
        min_count = int(self.params.get("min_count", 1))
        max_count = self.params.get("max_count")

        if server not in ctx.mock_states:
            return False, f"no state for mock server '{server}'"

        matches = _matches(ctx.mock_states[server], jsonpath)
        n = len(matches)
        if n < min_count:
            return False, f"{jsonpath}: {n} match(es), need >= {min_count}"
        if max_count is not None and n > int(max_count):
            return False, f"{jsonpath}: {n} match(es), need <= {max_count}"
        return True, f"{jsonpath}: {n} match(es)"
