# Copilot Instructions — my-tracks

See [docs/AGENTS.md](../docs/AGENTS.md) for full agent definitions, workflow requirements, and quality gates.

## Critical: Start of every session

Before doing anything else, run both commands in order:

```bash
~/work/ai/repository-helpers/scripts/dev/start-development --refresh
~/work/ai/repository-helpers/scripts/dev/start-development
```

- **`--refresh`**: syncs main with Graphite, prunes merged worktrees/branches, pulls latest main, ensures the service is running. Exits without creating a worktree.
- **plain**: repeats cleanup, then prompts for a new worktree name.
- Both are required — `--refresh` is the only invocation that checks/starts the service; the plain invocation is the only one that creates the worktree.

## Package manager

Use `uv` — never `pip` or `poetry`.

## Pull request workflow

1. Complete all pre-PR quality gates (pyright → ruff check → ruff format --check → pytest ≥90% coverage).
2. Create branch + PR with Graphite: `gt create --all --message "…"` then `gt submit --no-interactive --publish`.
3. Wait for CI to pass, then inform the user — do **not** merge or add labels without explicit approval.
4. On approval: `gh pr edit <pr> --add-label "merge-mq"` (submits to merge queue). Never use `merge-it`.
