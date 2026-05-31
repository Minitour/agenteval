"""Filesystem assertions evaluated against the ephemeral workspace.

file_exists      { path }
file_contains    { path, values: [...], mode: all|any (default all) }
dir_has_new_file { path, matches: glob (default '*'), contents_include: [...] }
"""
from __future__ import annotations

from .base import AssertContext, Assertion


class FileExistsAssertion(Assertion):
    kind = "file_exists"

    def evaluate(self, ctx: AssertContext) -> tuple[bool, str]:
        rel = self._require("path")
        target = ctx.workspace / rel
        return (target.exists(), f"{rel} {'exists' if target.exists() else 'missing'}")


class FileContainsAssertion(Assertion):
    kind = "file_contains"

    def evaluate(self, ctx: AssertContext) -> tuple[bool, str]:
        rel = self._require("path")
        values = self._require("values")
        mode = self.params.get("mode", "all")
        target = ctx.workspace / rel
        if not target.exists():
            return False, f"{rel} missing"
        text = target.read_text(errors="replace")
        present = [v for v in values if str(v) in text]
        missing = [v for v in values if str(v) not in text]
        ok = (len(missing) == 0) if mode == "all" else (len(present) > 0)
        return ok, f"{rel}: found {present}; missing {missing}"


class DirHasNewFileAssertion(Assertion):
    kind = "dir_has_new_file"

    def evaluate(self, ctx: AssertContext) -> tuple[bool, str]:
        rel = self._require("path")
        pattern = self.params.get("matches", "*")
        contents_include = self.params.get("contents_include", [])
        base = ctx.workspace / rel
        if not base.is_dir():
            return False, f"{rel} is not a directory"
        candidates = list(base.glob(pattern))
        if not candidates:
            return False, f"no file matching '{pattern}' in {rel}"
        if not contents_include:
            return True, f"{len(candidates)} file(s) match '{pattern}'"
        for f in candidates:
            text = f.read_text(errors="replace")
            if all(str(v) in text for v in contents_include):
                return True, f"{f.name} contains all of {contents_include}"
        return False, f"no '{pattern}' file in {rel} contains all of {contents_include}"
