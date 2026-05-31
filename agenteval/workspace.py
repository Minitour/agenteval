"""Ephemeral per-run workspace management.

Each run gets a fresh directory seeded from the scenario's assets/ so that file
side effects are isolated and reproducible. Workspaces live under
<project>/.agenteval-runtime/ and are removed after the run unless kept.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional


class Workspace:
    def __init__(self, root: Path, run_id: str):
        self.path = (root / ".agenteval-runtime" / "workspaces" / run_id).resolve()

    def create(self, assets_dir: Optional[Path]) -> Path:
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)
        self.path.mkdir(parents=True, exist_ok=True)
        if assets_dir and assets_dir.is_dir():
            # Copy assets into the workspace root (contents, not the dir itself).
            for child in assets_dir.iterdir():
                dst = self.path / child.name
                if child.is_dir():
                    shutil.copytree(child, dst)
                else:
                    shutil.copy2(child, dst)
        return self.path

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
