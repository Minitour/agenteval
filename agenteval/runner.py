"""Orchestration: setup -> run -> assert -> teardown, repeated and aggregated.

For each (scenario, model, repeat) the runner creates an isolated workspace,
starts the scenario's mock servers, installs the agent via the provider, runs
the prompt, snapshots mock state, evaluates assertions plus the optional judge,
and persists the per-run result immediately so a crash mid-suite keeps progress.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .assertions.base import AssertContext
from .assertions.judge import run_judge
from .assertions.registry import build_assertion
from .config import GlobalConfig
from .mocks.manager import MockManager
from .models import RunResult, Scenario, ScenarioResult
from .providers.base import Provider
from .workspace import Workspace

EchoFn = Callable[[str], None]


def _noop(_: str) -> None:
    pass


class Runner:
    def __init__(
        self,
        cfg: GlobalConfig,
        provider: Provider,
        *,
        no_judge: bool = False,
        keep_workspace: bool = False,
        echo: Optional[EchoFn] = None,
    ):
        self.cfg = cfg
        self.provider = provider
        self.no_judge = no_judge
        self.keep_workspace = keep_workspace
        self.echo = echo or _noop
        self.runs_dir = cfg.report_dir / "runs"

    # ── public API ────────────────────────────────────────────────────────

    def run_scenario(self, scenario: Scenario) -> list[ScenarioResult]:
        results: list[ScenarioResult] = []
        for model in scenario.run.models:
            sr = ScenarioResult(scenario_id=scenario.id, provider=self.provider.name, model=model)
            self.echo(f"\n  scenario '{scenario.id}'  provider={self.provider.name}  model={model}")
            for rep in range(1, scenario.run.repeats + 1):
                rr = self._run_once(scenario, model, rep)
                sr.runs.append(rr)
                self._persist(rr)
                self._echo_run(rr, rep, scenario.run.repeats)
            results.append(sr)
        return results

    # ── one execution ───────────────────────────────────────────────────────

    def _run_once(self, scenario: Scenario, model: str, rep: int) -> RunResult:
        run_id = f"{scenario.id}__{self.provider.name}__{model}__r{rep}__{uuid.uuid4().hex[:8]}"
        run_id = run_id.replace("/", "_").replace("[", "_").replace("]", "_")
        rr = RunResult(
            run_id=run_id,
            scenario_id=scenario.id,
            provider=self.provider.name,
            model=model,
            repeat_index=rep,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        ws = Workspace(self.cfg.root, run_id)
        workspace = ws.create(scenario.assets_dir)
        manager = MockManager(scenario.dir, scenario.mcp)

        try:
            endpoints = manager.start()
            agent_dir = self.cfg.agents_dir / scenario.agent
            self.provider.install(agent_dir=agent_dir, workspace=workspace, mock_endpoints=endpoints)

            env = dict(os.environ)
            t0 = time.monotonic()
            out = self.provider.run(
                prompt=scenario.prompt,
                workspace=workspace,
                model=model,
                timeout=scenario.run.timeout_seconds,
                max_turns=scenario.run.max_turns,
                env=env,
            )
            rr.duration_seconds = round(time.monotonic() - t0, 2)

            rr.input_tokens = out.input_tokens
            rr.output_tokens = out.output_tokens
            rr.cache_read_tokens = out.cache_read_tokens
            rr.cache_creation_tokens = out.cache_creation_tokens
            rr.total_cost_usd = out.total_cost_usd
            rr.num_turns = out.num_turns
            rr.final_output = out.final_output
            rr.exit_code = out.exit_code
            rr.error = out.error
            rr.tool_calls = manager.collect_tool_calls()
            mock_states = manager.snapshot_all()

            if out.error:
                rr.passed = False
                return rr

            actx = AssertContext(
                final_output=out.final_output,
                workspace=workspace,
                mock_states=mock_states,
                tool_calls=rr.tool_calls,
            )
            for spec in scenario.assertions:
                rr.assertions.append(build_assertion(spec).run(actx))

            self._maybe_judge(scenario, rr)
            rr.passed = self._compute_pass(scenario, rr)
        except Exception as exc:
            rr.error = f"runner error: {exc}"
            rr.passed = False
        finally:
            manager.stop()
            # Deregister from capa (and clean managed files) before deleting the
            # workspace, so each test leaves no entry behind in capa's database.
            # Skipped under --keep-workspace so the full installed state, capa
            # registration included, stays available for debugging.
            if not self.keep_workspace:
                try:
                    self.provider.teardown(workspace=workspace)
                except Exception:
                    pass
                ws.cleanup()
        return rr

    def _maybe_judge(self, scenario: Scenario, rr: RunResult) -> None:
        judge = scenario.judge
        if not judge or not judge.enabled or self.no_judge:
            return
        model = judge.model or self.cfg.judge_model
        outcome = run_judge(
            judge,
            scenario.dir,
            final_output=rr.final_output,
            tool_calls=rr.tool_calls,
            model=model,
            backend=self.cfg.judge_backend,
            cli=self.cfg.judge_cli,
        )
        rr.judge_score = outcome.score
        rr.judge_reasoning = outcome.reasoning or (outcome.error or "")

    def _compute_pass(self, scenario: Scenario, rr: RunResult) -> bool:
        if rr.error:
            return False
        if any(a.required and not a.passed for a in rr.assertions):
            return False
        judge = scenario.judge
        if judge and judge.enabled and not self.no_judge and judge.required:
            if rr.judge_score is None:
                return False
            if rr.judge_score < judge.min_score:
                return False
        return True

    # ── output + persistence ──────────────────────────────────────────────

    def _persist(self, rr: RunResult) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        (self.runs_dir / f"{rr.run_id}.json").write_text(
            json.dumps(asdict(rr), indent=2, default=str)
        )

    def _echo_run(self, rr: RunResult, rep: int, total: int) -> None:
        sym = "PASS" if rr.passed else "FAIL"
        if rr.error:
            self.echo(f"    trial {rep}/{total}: {sym}  error: {rr.error[:80]}")
            return
        failed = [a.label() for a in rr.assertions if not a.passed]
        judge = f"  judge={rr.judge_score:.2f}" if rr.judge_score is not None else ""
        detail = f"  failed={failed}" if failed else ""
        self.echo(
            f"    trial {rep}/{total}: {sym}  ${rr.total_cost_usd:.4f}  "
            f"turns={rr.num_turns}  {rr.duration_seconds:.1f}s{judge}{detail}"
        )

    def label(self) -> str:
        return self.provider.name
