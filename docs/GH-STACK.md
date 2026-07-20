# gh stack workflow

Stacking for this repository is selected by `.github/stacking-tool` (`gh-stack`).

**Agents:** follow the always-on cursor rule
[`.cursor/rules/stacking-tool.mdc`](../.cursor/rules/stacking-tool.mdc), which
points at the canonical playbook in repository-helpers:

- Skill: https://github.com/the-hcma/repository-helpers/blob/main/.cursor/skills/gh-stack/SKILL.md
- Local clone: `~/work/ai/repository-helpers/.cursor/skills/gh-stack/SKILL.md`

Prefer repository-helpers wrappers (`start-development`, `submit-stack`,
`ship-and-review`) from a **stack worktree**.

## Everyday commands (non-interactive)

| Action | Command |
| --- | --- |
| Session / worktree | `~/work/ai/repository-helpers/scripts/dev/start-development --worktree <stack> --no-interactive` |
| First layer | `gh stack init <stack>/<topic>` |
| Next layer | `gh stack add <stack>/<next>` |
| Submit | `~/work/ai/repository-helpers/scripts/dev/submit-stack` |
| View | `gh stack view --json` |
| Sync | `gh stack sync --remote origin` |

## Merge (GitHub merge queue)

```bash
gh pr merge <n> --auto --squash
```

Do **not** use retired Graphite enqueue labels (`merge-it`, `merge-mq`).
