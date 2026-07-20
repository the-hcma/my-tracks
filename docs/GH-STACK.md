# gh stack workflow

Stacking for this repository is selected by `.github/stacking-tool` (`gh-stack`).

**Agents:** follow the always-on cursor rule
[`.cursor/rules/stacking-tool.mdc`](../.cursor/rules/stacking-tool.mdc), which
points at the canonical playbook in repository-helpers:

- Skill: https://github.com/the-hcma/repository-helpers/blob/main/.cursor/skills/gh-stack/SKILL.md
- Local clone: `~/work/ai/repository-helpers/.cursor/skills/gh-stack/SKILL.md`

Run `start-development --refresh` from the **primary clone**, then create the
stack worktree (also from the primary clone). `cd` into
`.worktrees/<stack>-wt` before any implementation. Run `submit-stack` /
`ship-and-review` from that worktree only.

## Everyday commands (non-interactive)

| Action | Command |
| --- | --- |
| Refresh (primary clone) | `~/work/ai/repository-helpers/scripts/dev/start-development --refresh` |
| Create worktree (primary clone) | `~/work/ai/repository-helpers/scripts/dev/start-development --worktree <stack> --no-interactive` |
| Enter worktree | `cd .worktrees/<stack>-wt` |
| First layer | `gh stack init <stack>/<topic>` |
| Next layer | `gh stack add <stack>/<next>` |
| Submit (from worktree) | `~/work/ai/repository-helpers/scripts/dev/submit-stack` |
| View | `gh stack view --json` |
| Sync | `gh stack sync --remote origin` |

## Merge (GitHub merge queue)

```bash
gh pr merge <n> --auto --squash
```

Do **not** use retired Graphite enqueue labels (`merge-it`, `merge-mq`).
