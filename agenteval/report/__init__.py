"""Report emitters: JSON, JUnit XML, console, and markdown."""
from __future__ import annotations

from pathlib import Path

from ..models import ScenarioResult
from .console import render_console
from .json_report import write_json
from .junit import write_junit
from .markdown import write_markdown


def emit_all(results: list[ScenarioResult], report_dir: Path) -> dict[str, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": write_json(results, report_dir / "results.json"),
        "junit": write_junit(results, report_dir / "junit.xml"),
        "markdown": write_markdown(results, report_dir / "report.md"),
    }
    return paths
