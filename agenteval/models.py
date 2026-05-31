"""Core dataclasses shared across the framework.

These are deliberately plain dataclasses so they serialize cleanly with
`dataclasses.asdict` for the JSON report and stay provider-agnostic.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ── Scenario specification (parsed from scenario.yaml) ───────────────────────


@dataclass
class AssertionSpec:
    """A single declarative assertion as written in scenario.yaml.

    `kind` selects the assertion class; `params` is the remaining key/values
    from the YAML mapping. `required` failures fail the run (and the suite);
    non-required failures are reported but do not affect exit code.
    """

    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    required: bool = True
    name: str = ""

    def label(self) -> str:
        return self.name or self.kind


@dataclass
class JudgeSpec:
    """Optional LLM-as-judge configuration for a scenario."""

    enabled: bool = True
    rubric_file: Optional[str] = None
    rubric: Optional[str] = None
    model: Optional[str] = None
    min_score: float = 0.0
    required: bool = True


@dataclass
class RunConfig:
    """How many times and how to run a scenario."""

    models: list[str] = field(default_factory=list)
    repeats: int = 1
    timeout_seconds: int = 300
    max_turns: int = 25


@dataclass
class Scenario:
    """A single test case discovered under scenarios/<id>/."""

    id: str
    dir: Path
    agent: str
    prompt: str
    description: str = ""
    provider: Optional[str] = None
    mcp: list[str] = field(default_factory=list)
    assets_dir: Optional[Path] = None
    assertions: list[AssertionSpec] = field(default_factory=list)
    judge: Optional[JudgeSpec] = None
    run: RunConfig = field(default_factory=RunConfig)


# ── Run-time results ─────────────────────────────────────────────────────────


@dataclass
class AssertionResult:
    kind: str
    name: str
    required: bool
    passed: bool
    detail: str = ""

    def label(self) -> str:
        return self.name or self.kind


@dataclass
class RunResult:
    """The outcome of a single (scenario, model, repeat) execution."""

    run_id: str
    scenario_id: str
    provider: str
    model: str
    repeat_index: int
    timestamp: str

    # token + cost metrics
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0
    duration_seconds: float = 0.0

    # behaviour
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    final_output: str = ""

    # outcome
    assertions: list[AssertionResult] = field(default_factory=list)
    judge_score: Optional[float] = None
    judge_reasoning: str = ""
    passed: bool = False
    error: Optional[str] = None
    exit_code: Optional[int] = None

    @property
    def total_context_in(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_creation_tokens

    def tool_call_names(self) -> list[str]:
        return [c.get("tool", "") for c in self.tool_calls]


# metrics aggregated across repeats; keep in one place so report + runner agree
AGGREGATE_METRICS = [
    "total_cost_usd",
    "num_turns",
    "duration_seconds",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "total_context_in",
]


@dataclass
class ScenarioResult:
    """Aggregate of all repeats for one (scenario, provider, model) cell."""

    scenario_id: str
    provider: str
    model: str
    runs: list[RunResult] = field(default_factory=list)

    @property
    def n_total(self) -> int:
        return len(self.runs)

    @property
    def n_pass(self) -> int:
        return sum(1 for r in self.runs if r.passed)

    @property
    def n_error(self) -> int:
        return sum(1 for r in self.runs if r.error)

    @property
    def pass_rate(self) -> float:
        return (self.n_pass / self.n_total) if self.n_total else 0.0

    def metric_value(self, run: RunResult, metric: str) -> float:
        if metric == "total_context_in":
            return float(run.total_context_in)
        return float(getattr(run, metric, 0) or 0)

    def aggregates(self) -> dict[str, dict[str, float]]:
        """mean / stddev / median / min / max per metric over non-errored runs."""
        ok = [r for r in self.runs if not r.error]
        out: dict[str, dict[str, float]] = {}
        for metric in AGGREGATE_METRICS:
            values = [self.metric_value(r, metric) for r in ok]
            if not values:
                out[metric] = {}
                continue
            out[metric] = {
                "mean": statistics.fmean(values),
                "stddev": statistics.stdev(values) if len(values) > 1 else 0.0,
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
                "n": float(len(values)),
            }
        # judge score is optional; include when present
        judged = [r.judge_score for r in ok if r.judge_score is not None]
        if judged:
            out["judge_score"] = {
                "mean": statistics.fmean(judged),
                "stddev": statistics.stdev(judged) if len(judged) > 1 else 0.0,
                "median": statistics.median(judged),
                "min": min(judged),
                "max": max(judged),
                "n": float(len(judged)),
            }
        return out
