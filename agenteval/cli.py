"""agenteval command-line interface.

  agenteval run        run the suite, emit reports, exit nonzero on failure
  agenteval list       list discovered scenarios
  agenteval validate   check project structure without calling any model
  agenteval init       scaffold a new eval project
"""
from __future__ import annotations

import sys
from pathlib import Path

import click

from .config import load_config
from .providers.registry import available as available_providers
from .providers.registry import get_provider
from .report import emit_all
from .report.console import render_console
from .runner import Runner
from .scenarios import ScenarioError, discover_scenarios, validate_scenario
from .templates import scaffold_project


@click.group()
@click.version_option(package_name="agenteval-framework")
def main() -> None:
    """Unit tests for agents, powered by capa's capabilities.yaml."""


# ── run ──────────────────────────────────────────────────────────────────────


@main.command()
@click.option("--root", default=".", type=click.Path(file_okay=False), help="Project root.")
@click.option("--filter", "name_filter", default=None, help="Only run scenarios whose id contains this.")
@click.option("--provider", default=None, help=f"Override provider. One of: {available_providers()}")
@click.option("--model", "models", multiple=True, help="Override model(s); repeatable.")
@click.option("--repeat", type=int, default=None, help="Override repeats per scenario.")
@click.option("--report-dir", default=None, type=click.Path(file_okay=False), help="Where to write reports.")
@click.option("--no-judge", is_flag=True, help="Skip the LLM judge even if scenarios define one.")
@click.option("--keep-workspace", is_flag=True, help="Do not delete ephemeral workspaces.")
@click.option("-v", "--verbose", is_flag=True, help="Print per-run detail.")
def run(root, name_filter, provider, models, repeat, report_dir, no_judge, keep_workspace, verbose) -> None:
    """Run scenarios and emit reports."""
    cfg = load_config(Path(root))
    if provider:
        cfg.provider = provider
    if report_dir:
        rd = Path(report_dir)
        cfg.report_dir = rd if rd.is_absolute() else cfg.root / rd

    try:
        scenarios = discover_scenarios(cfg, name_filter)
    except ScenarioError as exc:
        raise click.ClickException(str(exc))
    if not scenarios:
        raise click.ClickException("no scenarios matched")

    # CLI overrides are authoritative over per-scenario run config.
    for s in scenarios:
        if models:
            s.run.models = list(models)
        if repeat is not None:
            s.run.repeats = repeat

    prov = get_provider(cfg.provider, cfg.provider_config())
    missing = prov.preflight()
    if missing:
        for m in missing:
            click.echo(f"  prerequisite missing: {m}", err=True)
        raise click.ClickException("provider preflight failed")

    # Validate before spending tokens.
    problems = []
    for s in scenarios:
        problems += [f"[{s.id}] {p}" for p in validate_scenario(s, cfg)]
    if problems:
        for p in problems:
            click.echo(f"  invalid: {p}", err=True)
        raise click.ClickException("scenario validation failed")

    echo = click.echo if verbose else (lambda _: None)
    runner = Runner(cfg, prov, no_judge=no_judge, keep_workspace=keep_workspace, echo=echo)

    click.echo(f"agenteval: {len(scenarios)} scenario(s), provider={cfg.provider}")
    all_results = []
    for s in scenarios:
        all_results.extend(runner.run_scenario(s))

    paths = emit_all(all_results, cfg.report_dir)
    click.echo(render_console(all_results))
    click.echo(f"  reports: {paths['json']}  |  {paths['junit']}  |  {paths['markdown']}")

    total = sum(sr.n_total for sr in all_results)
    passed = sum(sr.n_pass for sr in all_results)
    sys.exit(0 if (passed == total and total) else 1)


# ── list ─────────────────────────────────────────────────────────────────────


@main.command(name="list")
@click.option("--root", default=".", type=click.Path(file_okay=False))
def list_scenarios(root) -> None:
    """List discovered scenarios."""
    cfg = load_config(Path(root))
    try:
        scenarios = discover_scenarios(cfg)
    except ScenarioError as exc:
        raise click.ClickException(str(exc))
    if not scenarios:
        click.echo("no scenarios found")
        return
    for s in scenarios:
        click.echo(
            f"  {s.id:<28} agent={s.agent:<12} mcp={s.mcp} "
            f"assertions={len(s.assertions)} judge={'yes' if s.judge else 'no'}"
        )


# ── validate ─────────────────────────────────────────────────────────────────


@main.command()
@click.option("--root", default=".", type=click.Path(file_okay=False))
def validate(root) -> None:
    """Validate project structure (no model calls)."""
    cfg = load_config(Path(root))
    try:
        scenarios = discover_scenarios(cfg)
    except ScenarioError as exc:
        raise click.ClickException(str(exc))

    problems = []
    for s in scenarios:
        for p in validate_scenario(s, cfg):
            problems.append(f"[{s.id}] {p}")

    if problems:
        for p in problems:
            click.echo(f"  {p}", err=True)
        raise click.ClickException(f"{len(problems)} problem(s) found")
    click.echo(f"  ok: {len(scenarios)} scenario(s) valid")


# ── init ─────────────────────────────────────────────────────────────────────


@main.command()
@click.argument("target", default=".", type=click.Path(file_okay=False))
def init(target) -> None:
    """Scaffold a new eval project at TARGET."""
    created = scaffold_project(Path(target))
    click.echo(f"  scaffolded eval project at {Path(target).resolve()}")
    for c in created:
        click.echo(f"    + {c}")
    click.echo("\n  next: set ANTHROPIC_API_KEY (or fill .env), then `agenteval run -v`")


if __name__ == "__main__":
    main()
