"""Lifecycle manager for a scenario's mock MCP servers.

Starts one MockServer per declared mock on an auto-allocated port, exposes the
endpoint map for provider install, snapshots state (with __calls__) after a
run, and tears everything down.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .engine import MockServer
from .spec import load_mock_spec


class MockManager:
    def __init__(self, scenario_dir: Path, server_names: list[str]):
        self.scenario_dir = Path(scenario_dir)
        self.server_names = server_names
        self.servers: dict[str, MockServer] = {}

    def start(self) -> dict[str, str]:
        """Start every mock; return {name: url}."""
        endpoints: dict[str, str] = {}
        for name in self.server_names:
            mock_dir = self.scenario_dir / "mcp" / name
            spec = load_mock_spec(mock_dir)
            server = MockServer(spec)
            server.start(port=0)
            self.servers[name] = server
            endpoints[name] = server.url
        return endpoints

    def reset(self) -> None:
        for server in self.servers.values():
            server.reset()

    def snapshot_all(self) -> dict[str, dict[str, Any]]:
        return {name: server.snapshot() for name, server in self.servers.items()}

    def collect_tool_calls(self) -> list[dict[str, Any]]:
        """Flatten __calls__ across all mocks, annotated with the server name."""
        calls: list[dict[str, Any]] = []
        for name, server in self.servers.items():
            for call in server.snapshot().get("__calls__", []):
                calls.append(
                    {
                        "server": name,
                        "tool": call.get("tool"),
                        "args": call.get("args", {}),
                        "at": call.get("at"),
                    }
                )
        calls.sort(key=lambda c: c.get("at") or "")
        return calls

    def stop(self) -> None:
        for server in self.servers.values():
            try:
                server.stop()
            except Exception:
                pass
        self.servers.clear()

    def __enter__(self) -> "MockManager":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
