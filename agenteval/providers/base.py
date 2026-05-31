"""Provider abstraction.

A Provider knows how to (1) install an agent's capabilities into a workspace
for its harness and (2) run a prompt, returning normalized metrics. capa is
the bridge that compiles capabilities.yaml into provider-specific config;
concrete providers call the right `capa install -p <provider>` and the right
agent CLI. Add a new provider by subclassing Provider and registering it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class ProviderRunOutput:
    """Normalized result of a single agent invocation."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0
    final_output: str = ""
    exit_code: Optional[int] = None
    error: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


class Provider(ABC):
    name: str = "base"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    @abstractmethod
    def install(
        self,
        *,
        agent_dir: Path,
        workspace: Path,
        mock_endpoints: dict[str, str],
    ) -> None:
        """Compile the agent's capabilities.yaml into the workspace, wiring the
        declared MCP servers to the supplied local mock endpoints."""

    @abstractmethod
    def run(
        self,
        *,
        prompt: str,
        workspace: Path,
        model: str,
        timeout: int,
        max_turns: int,
        env: dict[str, str],
    ) -> ProviderRunOutput:
        """Run one prompt in the workspace and return normalized metrics."""

    def teardown(self, *, workspace: Path) -> None:
        """Undo whatever install() registered outside the workspace.

        Called after every run (before the workspace is deleted) so the run
        leaves nothing behind in capa's database or the provider's client
        config. Best effort; default is a no-op for providers that register
        nothing externally.
        """

    def preflight(self) -> list[str]:
        """Return a list of missing prerequisites (binaries, env). Empty = ready."""
        return []
