"""Discover and parse scenarios from a project's scenarios/ directory."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import GlobalConfig
from .models import AssertionSpec, JudgeSpec, RunConfig, Scenario


class ScenarioError(Exception):
    pass


def _parse_assertions(raw: list[dict[str, Any]]) -> list[AssertionSpec]:
    specs: list[AssertionSpec] = []
    for i, item in enumerate(raw or []):
        if not isinstance(item, dict) or "kind" not in item:
            raise ScenarioError(f"assertion #{i} must be a mapping with a 'kind'")
        params = {k: v for k, v in item.items() if k not in ("kind", "required", "name")}
        specs.append(
            AssertionSpec(
                kind=item["kind"],
                params=params,
                required=bool(item.get("required", True)),
                name=item.get("name", ""),
            )
        )
    return specs


def _parse_judge(raw: dict[str, Any] | None, cfg: GlobalConfig) -> JudgeSpec | None:
    if not raw:
        return None
    return JudgeSpec(
        enabled=bool(raw.get("enabled", True)),
        rubric_file=raw.get("rubric_file"),
        rubric=raw.get("rubric"),
        model=raw.get("model", cfg.judge_model),
        min_score=float(raw.get("min_score", cfg.judge_min_score)),
        required=bool(raw.get("required", True)),
    )


def _parse_run(raw: dict[str, Any] | None, cfg: GlobalConfig) -> RunConfig:
    raw = raw or {}
    return RunConfig(
        models=list(raw.get("models", cfg.models)),
        repeats=int(raw.get("repeats", cfg.repeats)),
        timeout_seconds=int(raw.get("timeout_seconds", cfg.timeout_seconds)),
        max_turns=int(raw.get("max_turns", cfg.max_turns)),
    )


def load_scenario(scenario_dir: Path, cfg: GlobalConfig) -> Scenario:
    spec_path = scenario_dir / "scenario.yaml"
    if not spec_path.exists():
        raise ScenarioError(f"{scenario_dir} has no scenario.yaml")
    raw = yaml.safe_load(spec_path.read_text()) or {}

    sid = raw.get("id", scenario_dir.name)

    # Prompt: inline `prompt:` wins, else `prompt_file:` (default input/prompt.md).
    prompt = raw.get("prompt")
    if prompt is None:
        prompt_file = raw.get("prompt_file", "input/prompt.md")
        p = scenario_dir / prompt_file
        if not p.exists():
            raise ScenarioError(f"scenario '{sid}': prompt missing ({p})")
        prompt = p.read_text()
    prompt = str(prompt).strip()

    if not raw.get("agent"):
        raise ScenarioError(f"scenario '{sid}': 'agent' is required")

    assets = raw.get("assets")
    assets_dir: Path | None = None
    if assets:
        assets_dir = (scenario_dir / assets).resolve()
    elif (scenario_dir / "assets").is_dir():
        assets_dir = (scenario_dir / "assets").resolve()

    return Scenario(
        id=sid,
        dir=scenario_dir.resolve(),
        agent=raw["agent"],
        prompt=prompt,
        description=raw.get("description", ""),
        mcp=list(raw.get("mcp", [])),
        assets_dir=assets_dir,
        assertions=_parse_assertions(raw.get("assertions", [])),
        judge=_parse_judge(raw.get("judge"), cfg),
        run=_parse_run(raw.get("run"), cfg),
    )


def discover_scenarios(cfg: GlobalConfig, name_filter: str | None = None) -> list[Scenario]:
    base = cfg.scenarios_dir
    if not base.is_dir():
        raise ScenarioError(f"no scenarios/ directory at {base}")
    out: list[Scenario] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or not (child / "scenario.yaml").exists():
            continue
        scenario = load_scenario(child, cfg)
        if name_filter and name_filter not in scenario.id:
            continue
        out.append(scenario)
    return out


def validate_scenario(scenario: Scenario, cfg: GlobalConfig) -> list[str]:
    """Return a list of human-readable problems; empty means valid."""
    problems: list[str] = []

    agent_dir = cfg.agents_dir / scenario.agent
    if not (agent_dir / "capabilities.yaml").exists():
        problems.append(
            f"agent '{scenario.agent}' has no capabilities.yaml at {agent_dir}"
        )

    for name in scenario.mcp:
        mock_dir = scenario.dir / "mcp" / name
        if not (mock_dir / "mock.yaml").exists():
            problems.append(f"mcp server '{name}' has no mock.yaml at {mock_dir}")

    if not scenario.assertions and not scenario.judge:
        problems.append("scenario has neither assertions nor a judge; nothing to check")

    if not scenario.run.models:
        problems.append("no models configured (set run.models or top-level models)")

    if scenario.judge:
        rf = scenario.judge.rubric_file
        if rf and not (scenario.dir / rf).exists():
            problems.append(f"judge.rubric_file not found: {scenario.dir / rf}")
        if not rf and not scenario.judge.rubric:
            problems.append("judge configured without rubric or rubric_file")

    return problems
