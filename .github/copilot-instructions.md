# Copilot Instructions — my-tracks

See [docs/AGENTS.md](../docs/AGENTS.md) for full agent definitions, workflow requirements, and quality gates.

## Critical: Start of every session

Before doing anything else, run both commands in order:

```bash
~/work/ai/repository-helpers/scripts/dev/start-development --refresh
~/work/ai/repository-helpers/scripts/dev/start-development
```

- **`--refresh`**: marker-aware sync (`.github/stacking-tool` is `gh-stack`), prunes merged worktrees/branches, pulls latest main, ensures the service is running. Exits without creating a worktree.
- **Second invocation** (required): creates the stack worktree — plain `start-development` (prompts for a name) or `--worktree <stack-name> --no-interactive`.
- Both are required — `--refresh` checks/starts the service; the second invocation (interactive or `--worktree`) creates the worktree.

## Package manager

Use `uv` — never `pip` or `poetry`.

## Pull request workflow

1. Complete all pre-PR quality gates (pyright → ruff check → ruff format --check → pytest ≥90% coverage).
2. Create branch + PR with **gh stack**: `gh stack init <stack>/<topic>`, commit, then `~/work/ai/repository-helpers/scripts/dev/submit-stack` (or `gh stack submit --auto --open --remote origin`).
3. Wait for CI to pass, then inform the user — do **not** merge without explicit approval.
4. On approval: `gh pr merge <pr> --auto --squash` (GitHub merge queue). Never use `merge-it` or `merge-mq`.
