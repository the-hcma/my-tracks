**Read [`AGENTS.md`](../AGENTS.md) at the repo root first — it is the single source of truth for this repo, and it tells you to also load every `alwaysApply: true` rule under `.agents/rules/`.**

---

# Copilot Instructions — my-tracks

See [AGENTS.md](../AGENTS.md) for full agent definitions, workflow requirements, and quality gates.

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
4. Merge only after the user explicitly confirms, and only with `${REPOSITORY_HELPERS_DIR:-$HOME/work/ai/repository-helpers}/scripts/dev/merge-stack --pr <n>` from the PR's worktree: it picks the right command for the repository's merge setup (`gh stack merge` for a stacked PR, the merge queue or auto-merge otherwise) and confirms the enqueue. For a PR in a gh stack, pass the top PR's number and run it from that stack's worktree: it refuses a lower layer, and it lands the top PR and every open PR below it, so name those PRs and get confirmation for the whole stack first. Do not call `gh pr merge` or `gh stack merge` by hand, do not add the `merge-it` label, and do not pipe the command through `tail` or `head`: read its exit status and output.
