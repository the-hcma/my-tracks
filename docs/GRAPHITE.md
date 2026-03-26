# Graphite Workflow

Reference guide for working with Graphite (`gt`) for creating, navigating, and managing stacked pull requests.

> **Project requirements:**
> - All `gt` commands must be prefixed with `GRAPHITE_PROFILE=thehcma` (authentication will fail otherwise)
> - Always include `--publish` when submitting PRs (omitting it creates draft PRs instead of ready-for-review)
> - Run `GRAPHITE_PROFILE=thehcma gt sync --force` at the start of every session before any other work

## Quick Reference

| I want to... | Command |
|--------------|---------|
| Sync main at session start | `GRAPHITE_PROFILE=thehcma gt sync --force` |
| Create a new branch/PR (stage all) | `GRAPHITE_PROFILE=thehcma gt create --all -m "message"` |
| Amend current branch (stage all) | `GRAPHITE_PROFILE=thehcma gt modify --all -m "message"` |
| Navigate up the stack | `gt up` |
| Navigate down the stack | `gt down` |
| Jump to top of stack | `gt top` |
| Jump to bottom of stack | `gt bottom` |
| View stack structure | `GRAPHITE_PROFILE=thehcma gt log short` |
| Submit current branch | `GRAPHITE_PROFILE=thehcma gt submit --no-interactive --publish` |
| Submit entire stack | `GRAPHITE_PROFILE=thehcma gt submit --stack --no-interactive --publish` |
| Rebase stack on trunk | `GRAPHITE_PROFILE=thehcma gt restack` |
| Change branch parent | `GRAPHITE_PROFILE=thehcma gt track --parent <branch>` |
| Rename current branch | `GRAPHITE_PROFILE=thehcma gt rename <new-name>` |
| Move branch in stack | `GRAPHITE_PROFILE=thehcma gt move` |
| Switch branches | `gt checkout <branch>` |
| Check working tree | `gt status` |
| View changes | `gt diff` |

---

## What Makes a Good PR?

In roughly descending order of importance:

- **Atomic/hermetic** - independent of other changes; will pass CI and be safe to deploy on its own
- **Narrow semantic scope** - changes only to module X, or the same change across modules X, Y, Z
- **Small diff** - (heuristic) small total diff line count

**Do NOT worry about creating TOO MANY pull requests.** It is **always** preferable to create more pull requests than fewer.

**NO CHANGE IS TOO SMALL:** tiny PRs allow for the medium/larger-sized PRs to have more clarity.

Always argue in favor of creating more PRs, as long as they independently pass build.

---

## Branch Naming Conventions

When naming PRs in a stack, follow this syntax:

`terse-stack-feature-name/terse-description-of-change`

For example, a 4-PR stack:

```
auth-bugfix/reorder-args
auth-bugfix/improve-logging
auth-bugfix/improve-documentation
auth-bugfix/handle-401-status-codes
```

---

## Session Start

**CRITICAL**: Before any other work, sync main:

```bash
GRAPHITE_PROFILE=thehcma gt sync --force
```

This pulls the latest `main` and restacks all local branches. Skipping this causes stale-base-ref ejections from the merge queue when other PRs have merged since your last session.

---

## Creating a Stack

### Basic Workflow

1. Stage and create: `GRAPHITE_PROFILE=thehcma gt create --all -m "feat: description"`
2. Repeat for each PR in the stack
3. Submit: `GRAPHITE_PROFILE=thehcma gt submit --stack --no-interactive --publish`

Alternatively, stage manually then create:

```bash
git add <files>
GRAPHITE_PROFILE=thehcma gt create branch-name -m "commit message"
```

### Handle Untracked Branches (common with worktrees)

Before creating branches, check if the current branch is tracked:

```bash
GRAPHITE_PROFILE=thehcma gt branch info
```

If you see "ERROR: Cannot perform this operation on untracked branch":

**Option A (Recommended): Track temporarily, then re-parent**
1. Track current branch: `GRAPHITE_PROFILE=thehcma gt track -p main`
2. Create your stack normally with `gt create`
3. After creating ALL branches, re-parent your first new branch onto main:
   ```bash
   GRAPHITE_PROFILE=thehcma gt checkout <first-branch-of-your-stack>
   GRAPHITE_PROFILE=thehcma gt track -p main
   GRAPHITE_PROFILE=thehcma gt restack
   ```

**Option B: Stash changes and start from main**
1. `git stash`
2. `git checkout main && git pull`
3. `git checkout -b temp-working && git stash pop`
4. `GRAPHITE_PROFILE=thehcma gt track -p main && GRAPHITE_PROFILE=thehcma gt create ...`

---

## Navigating a Stack

```bash
# Move up one branch (toward top of stack)
gt up

# Move down one branch (toward trunk)
gt down

# Jump to top of stack
gt top

# Jump to bottom of stack (first branch above trunk)
gt bottom

# View the full stack structure
GRAPHITE_PROFILE=thehcma gt log short
```

---

## Modifying a Stack

### Amend Current Branch

```bash
# Stage all changes and amend
GRAPHITE_PROFILE=thehcma gt modify --all -m "updated commit message"

# Or stage selectively
git add <files>
GRAPHITE_PROFILE=thehcma gt modify -m "updated commit message"
```

### Reorder Branches

Use `GRAPHITE_PROFILE=thehcma gt move` to reorder branches in the stack.

### Re-parent a Stack

If you created a stack on top of a feature branch but want it based on main:

```bash
GRAPHITE_PROFILE=thehcma gt checkout <first-branch>
GRAPHITE_PROFILE=thehcma gt track --parent main
GRAPHITE_PROFILE=thehcma gt restack
```

### Rename a Branch

```bash
GRAPHITE_PROFILE=thehcma gt rename new-branch-name
```

---

## Resetting Commits to Unstaged Changes

If changes are already committed but you want to re-stack them differently:

```bash
# Reset the last commit, keeping changes unstaged
git reset HEAD^

# Reset multiple commits (e.g., last 2 commits)
git reset HEAD~2

# View the diff to understand what you're working with
git diff HEAD
```

---

## Before Submitting

### Verify Stack is Rooted on Main

```bash
GRAPHITE_PROFILE=thehcma gt log short
```

If the first branch has a parent other than `main`:
```bash
GRAPHITE_PROFILE=thehcma gt checkout <first-branch>
GRAPHITE_PROFILE=thehcma gt track -p main
GRAPHITE_PROFILE=thehcma gt restack
```

### Run Validation

After creating each PR, run all quality gates (see AGENTS.md for the full list):

```bash
uv run pyright
uv run isort --check-only --diff app config web_ui
uv run flake8 --config dev-tooling/.flake8 app config
uv run pytest --cov=app --cov-fail-under=90
```

If validation fails, fix the issue and amend: `GRAPHITE_PROFILE=thehcma gt modify --all -m "..."`

### PR Submission Time Window

**Only submit PRs after 6 PM local time on weekdays.** PRs may be submitted at any time on weekends.

---

## Submitting and Updating PRs

### Submit the Stack

```bash
# Submit current branch only
GRAPHITE_PROFILE=thehcma gt submit --no-interactive --publish

# Submit entire stack
GRAPHITE_PROFILE=thehcma gt submit --stack --no-interactive --publish
```

**CRITICAL**: Never omit `--publish` — it creates draft PRs instead of ready-for-review PRs.

### Update PR Descriptions

After submitting, use `gh pr edit` to set proper titles and descriptions.

**IMPORTANT:** Never use Bash heredocs for PR descriptions — shell escaping breaks markdown tables, code blocks, etc. Instead:

1. Write the full markdown content to a file
2. Use `gh pr edit` with `--body-file`:

```bash
gh pr edit <PR_NUMBER> --title "stack-name: description" --body-file /tmp/pr-body.md
```

PR descriptions must include:
- **Stack Context**: What is the bigger goal of this stack?
- **What?** (optional for small changes): Super terse, focus on what not why
- **Why?**: What prompted the change? Why this solution? How does it fit into the stack?

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cannot perform this operation on untracked branch" | Run `GRAPHITE_PROFILE=thehcma gt track -p main` first |
| Stack parented on wrong branch | `GRAPHITE_PROFILE=thehcma gt track -p main` then `gt restack` |
| PR created as draft | Re-submit with `--publish` flag |
| Need to reorder PRs | Use `GRAPHITE_PROFILE=thehcma gt move` |
| Conflicts during restack | Resolve conflicts, then `git rebase --continue` |
| Want to split a PR | Reset commits (`git reset HEAD^`), re-stage selectively, create new branches |
| Need to delete a branch (non-interactive) | `GRAPHITE_PROFILE=thehcma gt delete <branch> -f -q` |
| `gt restack` hitting unrelated conflicts | Use targeted `git rebase <target>` instead (see below) |
| Rebase interrupted mid-conflict | Check if files are resolved but unstaged, then `git add` + `git rebase --continue` |
| Stale-base-ref ejection from merge queue | Run `GRAPHITE_PROFILE=thehcma gt sync --force` to resync |

---

## Advanced: Surgical Rebasing in Complex Stacks

In deeply nested stacks with many sibling branches, `gt restack` can be problematic:
- It restacks ALL branches that need it, not just your stack
- Can hit conflicts in completely unrelated branches
- Is all-or-nothing — hard to be surgical

### When to Use `git rebase` Instead of `gt restack`

Use direct `git rebase` when:
- You only want to update specific branches in your stack
- `gt restack` is hitting conflicts in unrelated branches
- You need to skip obsolete commits during the rebase

### Targeted Rebase Workflow

```bash
# 1. Checkout the branch you want to rebase
git checkout my-feature-branch

# 2. Rebase onto the target (e.g., updated parent branch)
git rebase target-branch

# 3. If you hit conflicts:
#    - Resolve the conflict in the file
#    - Stage it: git add <file>
#    - Continue: git rebase --continue

# 4. If a commit is obsolete and should be skipped:
git rebase --skip

# 5. After rebase, sync graphite's tracking
GRAPHITE_PROFILE=thehcma gt modify --no-edit
```

### Recovering from Interrupted Rebase (Context Reset)

If a rebase was interrupted (e.g., AI agent ran out of context):

1. **Check status:**
   ```bash
   git status
   # Look for "interactive rebase in progress" and "Unmerged paths"
   ```

2. **Read the "unmerged" files** — they may already be resolved (no conflict markers)

3. **If already resolved, just stage and continue:**
   ```bash
   git add <resolved-files>
   git rebase --continue
   ```

4. **If still has conflict markers**, resolve them first, then stage and continue

### Deleting Branches from a Stack

```bash
# Delete a branch (non-interactive, even if not merged)
GRAPHITE_PROFILE=thehcma gt delete branch-to-delete -f -q

# Also delete all children (upstack)
GRAPHITE_PROFILE=thehcma gt delete branch-to-delete -f -q --upstack

# Also delete all ancestors (downstack)
GRAPHITE_PROFILE=thehcma gt delete branch-to-delete -f -q --downstack
```

**Flags:**
- `-f` / `--force`: Delete even if not merged or closed
- `-q` / `--quiet`: Implies `--no-interactive`, minimizes output

**After deleting intermediate branches**, children are automatically restacked onto the parent. If you need to manually update tracking:
```bash
gt checkout child-branch
GRAPHITE_PROFILE=thehcma gt track --parent new-parent-branch
```
