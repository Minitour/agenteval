"""Assertion base class and the evaluation context handed to each assertion."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import AssertionResult, AssertionSpec


@dataclass
class AssertContext:
    """Everything an assertion can inspect about a finished run."""

    final_output: str
    workspace: Path
    mock_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class Assertion(ABC):
    kind: str = "base"

    def __init__(self, spec: AssertionSpec):
        self.spec = spec
        self.params = spec.params

    @abstractmethod
    def evaluate(self, ctx: AssertContext) -> tuple[bool, str]:
        """Return (passed, human-readable detail)."""

    def run(self, ctx: AssertContext) -> AssertionResult:
        try:
            passed, detail = self.evaluate(ctx)
        except Exception as exc:  # a broken assertion fails loudly but safely
            passed, detail = False, f"assertion error: {exc}"
        return AssertionResult(
            kind=self.kind,
            name=self.spec.label(),
            required=self.spec.required,
            passed=passed,
            detail=detail,
        )

    def _require(self, key: str) -> Any:
        if key not in self.params:
            raise KeyError(f"{self.kind}: missing required param '{key}'")
        return self.params[key]
