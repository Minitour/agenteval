"""agenteval command-line interface.

  agenteval run        run the suite, emit reports, exit nonzero on failure
  agenteval list       list discovered scenarios
  agenteval validate   check project structure without calling any model
  agenteval init       scaffold a new eval project
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import click

from .config import GlobalConfig, load_config
from .providers.registry import available as available_providers
from .providers.registry import get_provider
from .report import emit_all
from .report.console import render_console
from .runner import Runner
from .scenarios import ScenarioError, discover_scenarios, validate_scenario
from .templates import scaffold_project


class _ProviderOption(click.Option):
    """A --provider option whose help lists providers registered *now*.

    click bakes the `help` string at module-import time, so a provider added
    via the documented `register()` extension API (e.g. from a CLI wrapper)
    would otherwise never show up. Recomputing the help when the record is
    rendered keeps it in sync with the live registry.
    """

    def get_help_record(self, ctx: click.Context):
        self.help = f"Override provider. One of: {available_providers()}"
        return super().get_help_record(ctx)


def _load_plugins(cfg: GlobalConfig) -> None:
    """Import every module listed under `plugins:` in agenteval.yaml.

    Importing the module runs its top-level `register(MyProvider)` call, so a
    custom provider becomes usable without a hand-rolled CLI wrapper. The
    project root is added to sys.path so project-local modules (e.g.
    `providers.my_provider`) import cleanly.
    """
    if not cfg.plugins:
        return
    root = str(cfg.root)
    if root not in sys.path:
        sys.path.insert(0, root)
    for module in cfg.plugins:
        try:
            importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 - surface any import failure to the user
            raise click.ClickException(f"failed to import plugin '{module}': {exc}")


@click.group()
@click.version_option(package_name="agenteval-framework")
def main() -> None:
    """Unit tests for agents, powered by capa's capabilities.yaml."""


# ── run ──────────────────────────────────────────────────────────────────────


@main.command()
@click.option("--root", default=".", type=click.Path(file_okay=False), help="Project root.")
@click.option("--filter", "name_filter", default=None, help="Only run scenarios whose id contains this.")
@click.option("--provider", default=None, cls=_ProviderOption)
@click.option("--agent", "agents", multiple=True, help="Override scenario agent(s); repeatable, expands to one cell each.")
@click.option("--model", "models", multiple=True, help="Override model(s); repeatable.")
@click.option("--repeat", type=int, default=None, help="Override repeats per scenario.")
@click.option("--report-dir", default=None, type=click.Path(file_okay=False), help="Where to write reports.")
@click.option("--no-judge", is_flag=True, help="Skip the LLM judge even if scenarios define one.")
@click.option("--keep-workspace", is_flag=True, help="Do not delete ephemeral workspaces.")
@click.option("-v", "--verbose", is_flag=True, help="Print per-run detail.")
def run(root, name_filter, provider, agents, models, repeat, report_dir, no_judge, keep_workspace, verbose) -> None:
    """Run scenarios and emit reports."""
    cfg = load_config(Path(root))
    if provider:
        cfg.provider = provider
    if report_dir:
        rd = Path(report_dir)
        cfg.report_dir = rd if rd.is_absolute() else cfg.root / rd

    # Import user plugins so any register() calls land before we resolve providers.
    _load_plugins(cfg)

    try:
        scenarios = discover_scenarios(cfg, name_filter, agent_override=list(agents) or None)
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

    # A scenario may pin its own provider (scenario.yaml `provider:`); anything
    # unpinned falls through to the global default. Build one instance per
    # provider actually in use and preflight each before spending tokens (a
    # provider nobody uses is never instantiated, so its preflight can't block).
    default_provider = cfg.provider
    needed = sorted({s.provider or default_provider for s in scenarios})
    providers: dict = {}
    preflight_failed = False
    for name in needed:
        try:
            prov = get_provider(name, cfg.provider_config(name))
        except KeyError as exc:
            raise click.ClickException(str(exc))
        missing = prov.preflight()
        if missing:
            for m in missing:
                click.echo(f"  prerequisite missing [{name}]: {m}", err=True)
            preflight_failed = True
        providers[name] = prov
    if preflight_failed:
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
    runner = Runner(
        cfg, providers, default_provider,
        no_judge=no_judge, keep_workspace=keep_workspace, echo=echo,
    )

    provider_label = ", ".join(needed)
    click.echo(f"agenteval: {len(scenarios)} scenario(s), provider={provider_label}")
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
    id_w = max(len(s.id) for s in scenarios)
    agent_w = max(len(s.agent) for s in scenarios)
    for s in scenarios:
        click.echo(
            f"  {s.id:<{id_w}}  agent={s.agent:<{agent_w}}  mcp={s.mcp} "
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
