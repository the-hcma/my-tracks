---
name: gh-stack
description: >
  Manage stacked branches and pull requests with the gh-stack GitHub CLI extension.
  Use when creating, submitting, rebasing, syncing, or navigating stacked PRs in this repo.
---

# gh-stack (my-tracks)

This repository's stacking backend is **`gh-stack`** (see `.github/stacking-tool`).

**Canonical playbook** (follow this; do not invent flags):

- GitHub: https://github.com/the-hcma/repository-helpers/blob/main/.cursor/skills/gh-stack/SKILL.md
- Local clone: `~/work/ai/repository-helpers/.cursor/skills/gh-stack/SKILL.md`

## Non-interactive essentials

- `gh stack view --json` (never interactive TUI)
- `gh stack submit --auto --open --remote origin`
- Named `gh stack init <branch>` / `gh stack add <branch>` (never prompt for names)
- Prefer `~/work/ai/repository-helpers/scripts/dev/submit-stack` / `ship-and-review`

Do **not** mix with `gt create` / `gt submit` / `gt restack` on the same stack.
