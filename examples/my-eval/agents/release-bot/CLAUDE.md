# Workspace guidance

You are working inside a vendored copy of `tiangolo/full-stack-fastapi-template`
(commit `38302d7492dbd158ed6cf499a6dd0bab6ad17141`). The repo holds:

- `backend/` — FastAPI app with SQLModel-based `User` and `Item` resources,
  JWT login, and Alembic migrations.
- `frontend/` — React + TypeScript SPA.
- `docs/` — project documentation; benchmark tasks may write here.

## Reproducibility rules

These apply on every task in this workspace:

1. **No network reads for documentation lookups.** Use the Context7 plugin if
   you need library docs — never `curl` or `WebFetch` documentation sites.
2. **No git operations.** Never `git commit`, `git push`, or otherwise mutate
   git history. Treat the working tree as ephemeral.
3. **Stay inside the workspace.** Read/write only under `workspace/repo/`
   (your cwd). Do not touch absolute paths outside the repo.
4. **Do exactly what the task asks.** Don't speculatively expand scope, add
   tests, or refactor for style. Quality is judged against a per-task rubric;
   gold-plating hurts the rubric.

## Tooling

You have:

- Standard Claude Code built-ins (Read, Write, Edit, Bash, Glob, Grep, etc.).
- The MCP plugins listed in `.mcp.json` (slack, github, sentry, supabase,
  context7 — varies by scale). Their per-plugin skills live in
  `.claude/skills/<plugin>/SKILL.md` — read those for invocation patterns.

When a task says "post to Slack" or "open a GitHub issue", actually invoke
the corresponding plugin tool. Do not simulate or describe the action.

## Output

Keep your final response concise — a short success acknowledgement plus any
artifact links (e.g. the message permalink Slack returns). Do not echo back
the entire prompt.
