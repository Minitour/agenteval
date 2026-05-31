"""LLM-as-judge: score a run's quality against a rubric.

Two backends, selected by config:

  - "claude-cli" (default): shells out to `claude --print --output-format json`.
    Reuses whatever auth the Claude Code CLI already has (subscription or API
    key), so it works on machines that don't export ANTHROPIC_API_KEY.
  - "anthropic-api": uses the Anthropic Python SDK with ANTHROPIC_API_KEY.

The judge returns a score in [0, 1] plus short reasoning. A scenario gates on
`min_score`; failing the gate fails the run when the judge is required.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ..models import JudgeSpec

JUDGE_INSTRUCTIONS = (
    "You are a strict evaluation judge for an AI agent's output. You are given a "
    "rubric, the agent's final answer, and the tool calls it made. Score how well "
    "the agent satisfied the rubric. Respond with ONLY a JSON object of the form "
    '{"score": <float between 0 and 1>, "reasoning": <one or two sentences>}. '
    "Do not include any other text, markdown, or code fences."
)


@dataclass
class JudgeOutcome:
    score: Optional[float]
    reasoning: str
    error: Optional[str] = None


def _load_rubric(spec: JudgeSpec, scenario_dir: Path) -> str:
    if spec.rubric:
        return spec.rubric
    if spec.rubric_file:
        return (scenario_dir / spec.rubric_file).read_text()
    return ""


def _build_prompt(rubric: str, final_output: str, tool_calls: list[dict[str, Any]]) -> str:
    calls = [{"server": c.get("server"), "tool": c.get("tool"), "args": c.get("args")} for c in tool_calls]
    return (
        f"{JUDGE_INSTRUCTIONS}\n\n"
        f"# Rubric\n{rubric}\n\n"
        f"# Agent final answer\n{final_output or '(empty)'}\n\n"
        f"# Tool calls (in order)\n{json.dumps(calls, indent=2, default=str)}\n\n"
        "Score the agent against the rubric now. Output only the JSON object."
    )


def _extract_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group())
    raise ValueError(f"judge returned non-JSON: {text[:200]}")


def _finalize(text: str) -> JudgeOutcome:
    parsed = _extract_json(text)
    score = max(0.0, min(1.0, float(parsed.get("score"))))
    return JudgeOutcome(score, str(parsed.get("reasoning", "")))


def _judge_via_cli(prompt: str, model: str, cli: str) -> JudgeOutcome:
    cmd = [cli, "--print", "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)
    try:
        proc = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180
        )
    except subprocess.TimeoutExpired:
        return JudgeOutcome(None, "", error="judge cli timeout")
    except FileNotFoundError:
        return JudgeOutcome(None, "", error=f"judge cli '{cli}' not found")
    if not proc.stdout.strip():
        return JudgeOutcome(None, "", error=f"judge cli empty output: {proc.stderr[-300:]}")
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        return _finalize(str(data.get("result", "")))
    except Exception as exc:
        return JudgeOutcome(None, "", error=f"judge cli parse failed: {exc}")


def _judge_via_api(prompt: str, model: str, api_key: str) -> JudgeOutcome:
    try:
        import anthropic
    except ImportError:
        return JudgeOutcome(None, "", error="anthropic package not installed")
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return _finalize(text)
    except Exception as exc:
        return JudgeOutcome(None, "", error=f"judge api call failed: {exc}")


def run_judge(
    spec: JudgeSpec,
    scenario_dir: Path,
    *,
    final_output: str,
    tool_calls: list[dict[str, Any]],
    model: str,
    backend: str = "claude-cli",
    cli: str = "claude",
    api_key: Optional[str] = None,
) -> JudgeOutcome:
    rubric = _load_rubric(spec, scenario_dir)
    prompt = _build_prompt(rubric, final_output, tool_calls)

    if backend == "anthropic-api":
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return JudgeOutcome(None, "", error="ANTHROPIC_API_KEY not set for anthropic-api judge")
        return _judge_via_api(prompt, model, key)

    return _judge_via_cli(prompt, model, cli)
