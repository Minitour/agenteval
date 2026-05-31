"""Project + global config loading.

A project is a directory that contains agenteval.yaml, an agents/ folder and a
scenarios/ folder. API keys are taken from the process environment and an
optional .env file at the project root; the framework never writes keys to
disk.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def load_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env loader (KEY=VALUE per line). Avoids a python-dotenv dep.

    Values may be optionally quoted. Lines starting with # and blank lines are
    ignored. Existing process environment variables take precedence and are
    not overwritten.
    """
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded


@dataclass
class GlobalConfig:
    root: Path
    provider: str = "claude"
    models: list[str] = field(default_factory=lambda: ["claude-opus-4-8"])
    repeats: int = 1
    timeout_seconds: int = 300
    max_turns: int = 25
    judge_enabled: bool = True
    judge_model: str = "claude-opus-4-8"
    judge_min_score: float = 0.0
    judge_backend: str = "claude-cli"
    judge_cli: str = "claude"
    report_dir: Path = field(default_factory=lambda: Path("reports"))
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def agents_dir(self) -> Path:
        return self.root / "agents"

    @property
    def scenarios_dir(self) -> Path:
        return self.root / "scenarios"

    def provider_config(self, name: str | None = None) -> dict[str, Any]:
        return self.providers.get(name or self.provider, {})


def load_config(root: Path) -> GlobalConfig:
    root = root.resolve()
    cfg_path = root / "agenteval.yaml"
    raw: dict[str, Any] = {}
    if cfg_path.exists():
        raw = yaml.safe_load(cfg_path.read_text()) or {}

    load_dotenv(root / ".env")

    judge = raw.get("judge", {}) or {}
    report = raw.get("report", {}) or {}
    report_dir = Path(report.get("dir", "reports"))
    if not report_dir.is_absolute():
        report_dir = root / report_dir

    return GlobalConfig(
        root=root,
        provider=raw.get("provider", "claude"),
        models=list(raw.get("models", ["claude-opus-4-8"])),
        repeats=int(raw.get("repeats", 1)),
        timeout_seconds=int(raw.get("timeout_seconds", 300)),
        max_turns=int(raw.get("max_turns", 25)),
        judge_enabled=bool(judge.get("enabled", True)),
        judge_model=judge.get("model", "claude-opus-4-8"),
        judge_min_score=float(judge.get("min_score", 0.0)),
        judge_backend=judge.get("backend", "claude-cli"),
        judge_cli=judge.get("cli", "claude"),
        report_dir=report_dir,
        providers=raw.get("providers", {}) or {},
        raw=raw,
    )
