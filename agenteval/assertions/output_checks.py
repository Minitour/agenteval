"""Assertions on the agent's final textual output.

output_contains { values: [...], mode: all|any (default all), ignore_case: bool }
output_matches  { pattern: <regex>, ignore_case: bool }
"""
from __future__ import annotations

import re

from .base import AssertContext, Assertion


class OutputContainsAssertion(Assertion):
    kind = "output_contains"

    def evaluate(self, ctx: AssertContext) -> tuple[bool, str]:
        values = self._require("values")
        mode = self.params.get("mode", "all")
        ignore_case = bool(self.params.get("ignore_case", False))
        hay = ctx.final_output.lower() if ignore_case else ctx.final_output

        def contains(v: str) -> bool:
            needle = str(v).lower() if ignore_case else str(v)
            return needle in hay

        present = [v for v in values if contains(v)]
        missing = [v for v in values if not contains(v)]
        ok = (len(missing) == 0) if mode == "all" else (len(present) > 0)
        return ok, f"output: found {present}; missing {missing}"


class OutputMatchesAssertion(Assertion):
    kind = "output_matches"

    def evaluate(self, ctx: AssertContext) -> tuple[bool, str]:
        pattern = self._require("pattern")
        flags = re.IGNORECASE if self.params.get("ignore_case") else 0
        ok = re.search(pattern, ctx.final_output, flags) is not None
        return ok, f"/{pattern}/ {'matched' if ok else 'did not match'}"
