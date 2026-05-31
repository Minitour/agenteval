"""Markdown report for PR comments / artifacts."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ..models import ScenarioResult


def _fmt(agg: dict, metric: str, money: bool = False) -> str:
    m = agg.get(metric)
    if not m:
        return "n/a"
    if money:
        return f"${m['mean']:.4f} ± {m['stddev']:.4f}"
    return f"{m['mean']:.1f} ± {m['stddev']:.1f}"


def write_markdown(results: list[ScenarioResult], path: Path) -> Path:
    total = sum(sr.n_total for sr in results)
    passed = sum(sr.n_pass for sr in results)
    verdict = "PASS" if (passed == total and total) else "FAIL"

    lines: list[str] = []
    lines.append("# agenteval report")
    lines.append("")
    lines.append(f"Generated {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append(f"Suite: **{passed}/{total} runs passed** -> **{verdict}**")
    lines.append("")
    lines.append("| scenario | provider/model | pass | cost (USD) | turns | judge |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for sr in results:
        agg = sr.aggregates()
        judge = agg.get("judge_score")
        judge_str = f"{judge['mean']:.2f}" if judge else "-"
        lines.append(
            f"| {sr.scenario_id} | {sr.provider}/{sr.model} | "
            f"{sr.n_pass}/{sr.n_total} | {_fmt(agg, 'total_cost_usd', money=True)} | "
            f"{_fmt(agg, 'num_turns')} | {judge_str} |"
        )

    # Per-run assertion detail for any failing run.
    failing = [(sr, r) for sr in results for r in sr.runs if not r.passed]
    if failing:
        lines.append("")
        lines.append("## Failures")
        lines.append("")
        for sr, r in failing:
            lines.append(f"### {sr.scenario_id} [{sr.provider}/{sr.model}] repeat {r.repeat_index}")
            if r.error:
                lines.append(f"- error: {r.error}")
            for a in r.assertions:
                if not a.passed:
                    lines.append(f"- [{a.kind}] {a.name}: {a.detail}")
            if r.judge_score is not None:
                lines.append(f"- judge_score: {r.judge_score} ({r.judge_reasoning})")
            lines.append("")

    path.write_text("\n".join(lines))
    return path
