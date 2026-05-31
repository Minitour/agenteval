"""Assertion registry: kind string -> Assertion subclass."""
from __future__ import annotations

from ..models import AssertionSpec
from .base import Assertion
from .file_checks import DirHasNewFileAssertion, FileContainsAssertion, FileExistsAssertion
from .mock_state import MockStateAssertion
from .output_checks import OutputContainsAssertion, OutputMatchesAssertion
from .tool_called import ToolCalledAssertion

_ASSERTIONS: dict[str, type[Assertion]] = {
    cls.kind: cls
    for cls in (
        MockStateAssertion,
        ToolCalledAssertion,
        FileExistsAssertion,
        FileContainsAssertion,
        DirHasNewFileAssertion,
        OutputContainsAssertion,
        OutputMatchesAssertion,
    )
}


def available() -> list[str]:
    return sorted(_ASSERTIONS)


def build_assertion(spec: AssertionSpec) -> Assertion:
    if spec.kind not in _ASSERTIONS:
        raise KeyError(f"unknown assertion kind '{spec.kind}'. available: {available()}")
    return _ASSERTIONS[spec.kind](spec)
