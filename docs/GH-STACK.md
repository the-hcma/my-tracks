# gh stack workflow

This repository uses **GitHub Stacked PRs** via the `gh stack` CLI extension
(`.github/stacking-tool` → `gh-stack`), not Graphite.

**Canonical skill (agents):**  
https://github.com/the-hcma/repository-helpers/blob/main/.cursor/skills/gh-stack/SKILL.md

Local clone: `~/work/ai/repository-helpers/.cursor/skills/gh-stack/SKILL.md`

## Session start

```bash
~/work/ai/repository-helpers/scripts/dev/start-development --refresh
~/work/ai/repository-helpers/scripts/dev/start-development --worktree <stack-name> --no-interactive
cd .worktrees/<stack-name>-wt
```

## Everyday commands (non-interactive)

| Action | Command |
| --- | --- |
| Create first stack layer | `gh stack init <stack>/<topic>` |
| Add a layer | `gh stack add <stack>/<next>` |
| Submit / update PRs | `~/work/ai/repository-helpers/scripts/dev/submit-stack` or `gh stack submit --auto --open --remote origin` |
| View stack | `gh stack view --json` |
| Sync / restack | `gh stack sync --remote origin` (or `gh stack rebase --remote origin`) |
| Navigate | `gh stack up` / `gh stack down` / `gh stack top` / `gh stack bottom` |

## Merge (GitHub merge queue)

After user approval:

```bash
gh pr merge <n> --auto --squash
```

Do **not** use Graphite enqueue labels (`merge-it`, `merge-mq`).

## Amend / fixups

Prefer a single commit per stack layer. Squash locally if needed, then
`gh stack submit --auto --open --remote origin` and monitor CI.
