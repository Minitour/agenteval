"""Full machine-readable JSON report."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ..models import ScenarioResult


def build_payload(results: list[ScenarioResult]) -> dict:
    cells = []
    for sr in results:
        cells.append(
            {
                "scenario_id": sr.scenario_id,
                "provider": sr.provider,
                "model": sr.model,
                "n_total": sr.n_total,
                "n_pass": sr.n_pass,
                "n_error": sr.n_error,
                "pass_rate": sr.pass_rate,
                "aggregates": sr.aggregates(),
                "runs": [asdict(r) for r in sr.runs],
            }
        )
    total = sum(sr.n_total for sr in results)
    passed = sum(sr.n_pass for sr in results)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "cells": len(results),
            "runs_total": total,
            "runs_passed": passed,
            "suite_pass": passed == total and total > 0,
        },
        "cells": cells,
    }


def write_json(results: list[ScenarioResult], path: Path) -> Path:
    path.write_text(json.dumps(build_payload(results), indent=2, default=str))
    return path
