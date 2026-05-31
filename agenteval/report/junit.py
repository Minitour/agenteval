"""JUnit XML report for native CI gating.

One <testsuite> per (scenario, model) cell; one <testcase> per repeat. A failed
repeat carries a <failure> with the failing assertions / error.
"""
from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

from ..models import RunResult, ScenarioResult


def _failure_message(run: RunResult) -> str:
    if run.error:
        return f"error: {run.error}"
    parts = [f"{a.name}: {a.detail}" for a in run.assertions if not a.passed]
    if run.judge_score is not None:
        parts.append(f"judge_score={run.judge_score}")
    return "; ".join(parts) or "failed"


def write_junit(results: list[ScenarioResult], path: Path) -> Path:
    root = Element("testsuites")
    total_tests = total_failures = total_errors = 0

    for sr in results:
        suite = SubElement(
            root,
            "testsuite",
            name=f"{sr.scenario_id}[{sr.provider}/{sr.model}]",
            tests=str(sr.n_total),
            failures=str(sr.n_total - sr.n_pass - sr.n_error),
            errors=str(sr.n_error),
        )
        for run in sr.runs:
            total_tests += 1
            case = SubElement(
                suite,
                "testcase",
                classname=f"{sr.scenario_id}.{sr.provider}.{sr.model}",
                name=f"repeat_{run.repeat_index}",
                time=str(run.duration_seconds),
            )
            if run.error:
                total_errors += 1
                err = SubElement(case, "error", message=_failure_message(run))
                err.text = run.error
            elif not run.passed:
                total_failures += 1
                fail = SubElement(case, "failure", message=_failure_message(run))
                fail.text = _failure_message(run)

    root.set("tests", str(total_tests))
    root.set("failures", str(total_failures))
    root.set("errors", str(total_errors))

    ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path
