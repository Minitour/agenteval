"""Human-readable console summary."""
from __future__ import annotations

from ..models import ScenarioResult


def render_console(results: list[ScenarioResult]) -> str:
    lines: list[str] = []
    lines.append("")
    lines.append("=" * 78)
    lines.append("  agenteval summary")
    lines.append("=" * 78)
    header = f"  {'scenario [provider/model]':<44} {'pass':>8} {'cost mean':>12}"
    lines.append(header)
    lines.append("  " + "-" * 74)

    total = passed = 0
    for sr in results:
        total += sr.n_total
        passed += sr.n_pass
        agg = sr.aggregates().get("total_cost_usd", {})
        cost = f"${agg['mean']:.4f}" if agg else "n/a"
        cell = f"{sr.scenario_id} [{sr.provider}/{sr.model}]"
        lines.append(f"  {cell:<44} {sr.n_pass:>3}/{sr.n_total:<3} {cost:>12}")

    lines.append("  " + "-" * 74)
    verdict = "PASS" if (passed == total and total) else "FAIL"
    lines.append(f"  suite: {passed}/{total} runs passed  ->  {verdict}")
    lines.append("")
    return "\n".join(lines)
