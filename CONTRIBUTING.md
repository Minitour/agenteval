# Contributing to agenteval

Thanks for helping improve [agenteval](https://github.com/Minitour/agenteval)!

## Quick start

```bash
git clone https://github.com/Minitour/agenteval.git
cd agenteval
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
agenteval --help
```

## Development

- **Runtime:** Python 3.9+
- **Install:** `pip install -e ".[dev]"` (pulls in `pytest`, `build`, `twine`)
- **Smoke test:** `agenteval validate` and `agenteval run --root examples/my-eval`
- **Build:** `python -m build`, then `twine check dist/*`

Running the example end to end needs the external `capa` binary and the
`claude` CLI on PATH; `validate` and the unit tests do not.

## Code style

- Type hints everywhere, `from __future__ import annotations` at the top of modules
- Standard library first; keep runtime dependencies minimal
- Match existing patterns in the module you're editing, don't drive-by refactor

## Pull requests

1. **One change per PR.** Keep it focused and reviewable.
2. **Tests for behavior changes**, and confirm the example still passes.
3. **`agenteval validate` must pass** before requesting review.
4. Link the related issue in the PR description.
5. Update the README when user-facing behavior changes.

Questions? Open an [issue](https://github.com/Minitour/agenteval/issues).
