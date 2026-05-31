"""Claude Code provider.

Install: compile the agent's capabilities.yaml into the workspace (wiring MCP
servers to local mock endpoints) and run `capa install -p claude-code`.
Run: invoke `claude --print --output-format json` headless, then normalize the
JSON result into ProviderRunOutput.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .base import Provider, ProviderRunOutput


class _CapaDumper(yaml.SafeDumper):
    """Dump multi-line strings (rule bodies) as literal blocks for readability."""


_CapaDumper.add_representer(
    str,
    lambda d, x: d.represent_scalar(
        "tag:yaml.org,2002:str", x, style="|" if "\n" in x else None
    ),
)


def compile_capabilities(agent_dir: Path, mock_endpoints: dict[str, str]) -> dict[str, Any]:
    """Load capabilities.yaml, prune to the live mock servers, rewrite URLs, and
    make local paths absolute so `capa install` resolves them from the workspace.
    """
    doc = yaml.safe_load((agent_dir / "capabilities.yaml").read_text()) or {}
    keep = set(mock_endpoints)

    # Servers: keep those backed by a mock, rewrite their URL to the mock port.
    servers = []
    for s in doc.get("servers", []) or []:
        if s.get("id") in keep:
            s.setdefault("def", {})["url"] = mock_endpoints[s["id"]]
            servers.append(s)
    if "servers" in doc:
        doc["servers"] = servers

    # Tools: keep those whose server is live.
    if "tools" in doc:
        doc["tools"] = [
            t
            for t in doc.get("tools", []) or []
            if str((t.get("def") or {}).get("server", "")).lstrip("@") in keep
        ]
    kept_tool_refs = {f"@{(t['def']['server']).lstrip('@')}.{t['def']['tool']}" for t in doc.get("tools", [])}

    # Skills: prune `requires` to kept tools; resolve local skill paths.
    for skill in doc.get("skills", []) or []:
        d = skill.get("def") or {}
        if "requires" in d:
            d["requires"] = [r for r in d["requires"] if r in kept_tool_refs]
        if "path" in d and not Path(d["path"]).is_absolute():
            d["path"] = str((agent_dir / d["path"]).resolve())

    # agents.base path -> absolute.
    base = (doc.get("agents") or {}).get("base") or {}
    if "path" in base and not Path(base["path"]).is_absolute():
        base["path"] = str((agent_dir / base["path"]).resolve())

    return doc


class ClaudeProvider(Provider):
    name = "claude"

    def preflight(self) -> list[str]:
        missing: list[str] = []
        if shutil.which(self.config.get("capa_bin", "capa")) is None:
            missing.append("capa binary not on PATH (see https://github.com/infragate/capa)")
        if shutil.which(self.config.get("cli", "claude")) is None:
            missing.append("claude CLI not on PATH (install Claude Code)")
        return missing

    def install(self, *, agent_dir: Path, workspace: Path, mock_endpoints: dict[str, str]) -> None:
        # Clean prior artifacts so capa starts from a known state.
        for name in (".claude", ".mcp.json", "capabilities.yaml", "capabilities.lock", "AGENTS.md", "CLAUDE.md"):
            target = workspace / name
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()

        compiled = compile_capabilities(agent_dir, mock_endpoints)
        (workspace / "capabilities.yaml").write_text(
            yaml.dump(compiled, Dumper=_CapaDumper, sort_keys=False, default_flow_style=False, width=120)
        )

        capa_bin = self.config.get("capa_bin", "capa")
        proc = subprocess.run(
            [capa_bin, "install", "-p", "claude-code"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"capa install failed (exit {proc.returncode}):\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}"
            )

        # CLI mode: some capabilities intentionally omit an MCP proxy. If capa
        # wrote no .mcp.json, synthesize an empty one so --strict-mcp-config is
        # happy and the agent reaches tools via `capa sh`.
        mcp_json = workspace / ".mcp.json"
        if not mcp_json.exists():
            mcp_json.write_text(json.dumps({"mcpServers": {}}))

    def teardown(self, *, workspace: Path) -> None:
        # `capa clean` removes the managed files and, importantly, unregisters
        # the MCP server and deletes the project entry from capa's database.
        # Run it in the workspace before the directory is deleted, otherwise the
        # entry is orphaned in capa for every run. Best effort.
        capa_bin = self.config.get("capa_bin", "capa")
        try:
            subprocess.run(
                [capa_bin, "clean"],
                cwd=str(workspace),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception:
            pass

    def run(
        self,
        *,
        prompt: str,
        workspace: Path,
        model: str,
        timeout: int,
        max_turns: int,
        env: dict[str, str],
    ) -> ProviderRunOutput:
        cli = self.config.get("cli", "claude")
        mcp_json = workspace / ".mcp.json"
        if not mcp_json.exists():
            mcp_json.write_text(json.dumps({"mcpServers": {}}))

        cmd = [
            cli,
            "--print",
            "--output-format",
            "json",
            "--strict-mcp-config",
            "--mcp-config",
            str(mcp_json),
            "--permission-mode",
            "bypassPermissions",
            "--max-turns",
            str(max_turns),
        ]
        if model:
            cmd += ["--model", model]
        cmd.append(prompt)

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ProviderRunOutput(error=f"timeout >{timeout}s", exit_code=-1)
        except FileNotFoundError:
            return ProviderRunOutput(error=f"{cli} not found", exit_code=127)

        return self._parse(proc.stdout, proc.stderr, proc.returncode)

    @staticmethod
    def _parse(stdout: str, stderr: str, exit_code: int) -> ProviderRunOutput:
        out = (stdout or "").strip()
        if not out:
            return ProviderRunOutput(error=f"empty output. stderr: {stderr[-500:]}", exit_code=exit_code)
        try:
            data = json.loads(out.splitlines()[-1])
        except json.JSONDecodeError:
            return ProviderRunOutput(error=f"unparseable output: {out[:500]}", exit_code=exit_code, raw={"stdout": out[:2000]})

        usage = data.get("usage", {}) or {}
        return ProviderRunOutput(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            total_cost_usd=float(data.get("total_cost_usd", 0.0) or 0.0),
            num_turns=int(data.get("num_turns", 0) or 0),
            final_output=str(data.get("result", "")),
            exit_code=exit_code,
            error=str(data.get("result", ""))[:500] if data.get("is_error") else None,
            raw=data,
        )
