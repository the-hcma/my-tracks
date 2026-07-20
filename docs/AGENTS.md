# Agent Definitions

This document defines the four specialized agents for the My Tracks project.

**Configuration**: See [AGENT_MODELS.md](./AGENT_MODELS.md) for model assignments and `.agent-models.json` for machine-readable configuration.

**Package Manager**: This project uses `uv` as the Python package manager for fast, reliable dependency management.

**Python Version Policy**: Always use the latest stable Python version available via Homebrew. Currently Python 3.14.x is the latest stable release. The project requires Python 3.14+ (`requires-python = ">=3.14"` in pyproject.toml).

**Spelling locale**: Use **American English** spelling in all new project-authored prose: user-visible web copy, Django `help_text` / `verbose_name`, API field descriptions, comments in new code, and documentation under `docs/` that this repository maintains. Prefer *meters*, *behavior*, *center*, *color*, and similar US forms—not *metres*, *behaviour*, *centre*, *colour*. Do **not** rewrite third-party literals (for example JSON keys, CSS properties such as `behaviour`, or upstream API names) when those spellings are required for correctness.

## Dependency release age (dep-updater 9 days, Dependabot 10 days)

New dependency versions are adopted on a staggered schedule so **dep-updater** (repository-helpers) lands updates before Dependabot (see [repository-helpers](https://github.com/the-hcma/repository-helpers) `AGENTS.md`).

| Layer | Mechanism |
|-------|-----------|
| **pnpm** (frontend) | `minimumReleaseAge: 12960` (9 days) in `pnpm-workspace.yaml`. `minimumReleaseAgeExclude: ["*"]` grandfathers the **existing lockfile at cutover** so CI keeps working. |
| **dep-updater** | 9-day gate for npm, Python/PyPI, and GitHub Actions bumps. |
| **Dependabot** | Weekly scan + `cooldown: default-days: 10` on **version-update** PRs in `.github/dependabot.yml` (pip, npm, github-actions; one day after dep-updater). Do **not** set `open-pull-requests-limit: 0` — version updates stay enabled as a backup. |

### Dependabot: version bumps vs security

- **Version updates** — Dependabot checks on the weekly schedule; each proposed bump must pass the **10-day cooldown** (release age). dep-updater usually lands the same bump first (9-day gate); Dependabot version PRs after that are redundant and can be closed.
- **Security updates** — **not** subject to the version-update cooldown. Dependabot may open a security PR as soon as GitHub has an alert and a fix; merge these promptly.
- **dep-updater CVE bypass** — when **npm audit** or **pip-audit** reports CVE IDs with an available fix, dep-updater skips the 9-day gate for that package only (`--security-only` mode is available).

**Day-to-day:** merge dep-updater batch PRs for routine bumps; close duplicate Dependabot version PRs when dep-updater already has the change. Re-run `scripts/grandfather-pnpm-release-age --wildcard` only if `pnpm-workspace.yaml` was lost after a major lockfile reset.

## Workflow Requirements

**CRITICAL**: All changes MUST go through pull requests - direct pushes to main are blocked by branch protection.

**At the start of every session**, before doing anything else:
1. **Initialize session** — run both commands in order ([repository-helpers](https://github.com/the-hcma/repository-helpers)):
   ```
   ~/work/ai/repository-helpers/scripts/dev/start-development --refresh
   ~/work/ai/repository-helpers/scripts/dev/start-development
   ```
   - **`--refresh`** (first): marker-aware sync via `.github/stacking-tool` (`gh-stack`), prunes merged worktrees and branches, pulls latest main, and ensures the background service is running (or installs it via `setup-service` if not yet configured). Exits immediately — it does **not** create a worktree.
   - **Second invocation** (required): creates the stack worktree — either interactive (plain `start-development`, prompts for a name) or non-interactive:
     ```bash
     ~/work/ai/repository-helpers/scripts/dev/start-development --worktree <stack-name> --no-interactive
     ```
   - Both commands are required: `--refresh` is the only one that checks/starts the service; the second invocation (plain or `--worktree … --no-interactive`) is what creates the worktree.
   - After `start-development` finishes, **`cd` into the stack worktree** (`.worktrees/<stack-name>-wt`) before any other work. Do not stay in the primary clone.

### Main worktree is off-limits (agents)

The **primary clone** (repo root — first entry in `git worktree list`, usually on branch `main`) is the **main worktree**. Treat it as **read-only** unless the user explicitly authorizes touching it in the current conversation.

**Never on the main worktree** (without explicit user authorization):

- Edit, create, or delete source files, config, or lockfiles
- Run `uv sync`, `pnpm install`, tests, builds, or formatters
- Run `dep-updater` with `--dir` pointing at the primary clone (it may fast-forward `main` and mutate git state)
- Run `gh stack` / `gt` / commits / checkouts or other git write operations
- Leave uncommitted changes, stray branches, or detached HEAD state

**Always** do implementation, investigation that mutates state, and validation in a **stack worktree** under `.worktrees/<stack-name>-wt`. Pass that path to tools (`--dir`, `cd`, etc.).

`start-development` may update the main worktree for environment sync only; that is not permission to work there. If you need to inspect `main` without changing it, use read-only commands (`git log`, `git show`, `gh pr view`) or a **detached temporary worktree** — not the primary clone.

**Before creating any pull request**, the following workflow MUST be completed:

1. **Implementation Agent** completes the code changes
2. **Primary Critique Agent (Claude)** reviews the implementation
3. **Secondary Critique Agent (GPT-5)** provides independent review
4. **Testing Agent** ensures comprehensive test coverage
5. **Final verification**: All agents confirm VS Code Problems panel is clear
6. **Coverage verification**: Run `uv run pytest --cov=app --cov-fail-under=90` and ensure it passes
7. **Create feature branch**: NEVER commit or push to main - always create a feature branch
8. **PR must be ready for review**:
   - The PR **must not be a draft**
   - The PR **must have a clear description** (Summary + Test plan at minimum)

**Pull Request Workflow** (CRITICAL):

1. **Create PR**: Once all pre-PR quality gates pass, create the pull request
2. **One commit per PR**: Each PR branch should have **exactly one commit** on top of its base when ready for review. Fold all implementation, review fixups, and CI fixups into that commit — do not leave a chain of `fix:` / `style:` commits on the branch.
3. **Wait for CI/CD**: After every push, **actively monitor** GitHub Actions until all checks pass or fail — do not push and stop. Poll with `gh pr checks <pr-number>` (see **GitHub Actions Polling** below). If CI fails, fix locally, squash/amend on the stack layer, resubmit with `gh stack submit --auto --open --remote origin`, and poll again.
4. **User Testing**: After CI passes, inform user that PR is ready for manual testing
5. **User Approval**: Wait for explicit user approval before proceeding
6. **Submit to merge queue**: Only after user approval, enable GitHub auto-merge: `gh pr merge <pr-number> --auto --squash`
7. **Cleanup**: After merge completes, `~/work/ai/repository-helpers/scripts/dev/start-development --refresh` (or `gh stack sync --remote origin`) to update local main and clean up branches

**DO NOT**:
- ❌ Create PR before all quality gates pass
- ❌ Ask user to test before CI/CD passes
- ❌ Merge PR without explicit user approval
- ❌ Skip waiting for CI/CD checks or push without monitoring CI to completion
- ❌ **Leave multiple commits on a PR branch** — squash to one commit before/at submit (see Branch Workflow)
- ❌ **Use Graphite enqueue labels** (`merge-it`, `merge-mq`) — this repo uses GitHub merge queue via auto-merge

> Stacking SSOT for agents: [`.cursor/rules/stacking-tool.mdc`](../.cursor/rules/stacking-tool.mdc)
> (canonical skill in repository-helpers). Short cheat sheet: [GH-STACK.md](./GH-STACK.md).

**Branch Workflow** (CRITICAL — Use `gh stack`):
- ✅ **ALWAYS** use `gh stack` (marker `.github/stacking-tool` = `gh-stack`) for branch and PR stacking
- ✅ Prefer `~/work/ai/repository-helpers/scripts/dev/submit-stack` / `ship-and-review`
- ✅ Non-interactive flags: `gh stack view --json`, `gh stack submit --auto --open --remote origin`, named `init`/`add`
- ✅ **Create stack**: `gh stack init <stack>/<topic>` then commit; add layers with `gh stack add <stack>/<next>`
- ✅ **One commit per PR layer**: Prefer a single commit on the branch. Squash before submit if needed.
- ✅ **Submit PRs**: `gh stack submit --auto --open --remote origin`, then patch description with `gh pr edit` / `gh api` as needed
- ✅ **View stack**: `gh stack view --json`
- ✅ **Sync**: `gh stack sync --remote origin` (or `gh stack rebase --remote origin`)
- ❌ **NEVER** mix `gt` and `gh stack` on the same stack
- ❌ **NEVER** commit or push directly to main
- ❌ **NEVER** add `Co-Authored-By: Claude` (or any AI attribution) to commit messages or PR descriptions
- Rationale: GitHub Stacked PRs keep review diffs focused; repository-helpers wrappers keep agents non-interactive.

**Branch Cleanup**:
- Periodically prune stale remote-tracking branches: `git fetch --prune`
- Delete local branches whose upstream is gone: `git branch -vv | grep ': gone]' | awk '{print $1}' | xargs -r git branch -D`
- Transitional: leftover `graphite-base/*` / `gtmq_*` branches are cleaned by scheduled workflows until gone
- Run cleanup after merging PRs or when branch list becomes cluttered
- Rationale: Keeps repository clean, avoids confusion from old branches

**Pre-PR Quality Gates** — complete ALL steps in order before considering a PR ready:

**Step 1 — Local checks** (catch issues before pushing):
```bash
uv run pyright                                      # type errors
uv run ruff check app config web_ui                 # lint + import order
uv run ruff format --check app config web_ui        # formatting
uv run pytest --cov=app --cov-fail-under=90   # tests + coverage
```
The first three checks (`pyright`, `ruff check`, `ruff format --check`) are independent and **should be run in parallel** to save time — start all three at once and wait for all to complete before proceeding. `pytest` must run separately after the others pass (it is slower and its output is the final gate). `pytest` itself already runs tests in parallel across all available CPU cores via `pytest-xdist` (`-n auto` is set in `pyproject.toml`'s `addopts`) — no extra flags needed.

Do not proceed if any of these fail. Fix first.

**Step 2 — Submit via gh stack** (pushes branches and updates PRs):
```bash
~/work/ai/repository-helpers/scripts/dev/submit-stack
# or: gh stack submit --auto --open --remote origin
```

**Step 2b — Monitor CI until complete** (mandatory after every push):
Prefer the stack-aware helper (waits on the PR for the current branch; for multi-PR stacks, check every open layer):
```bash
~/work/ai/repository-helpers/scripts/dev/post-pr-submission-checks --pr <pr-number>
# Multi-PR stack: enumerate layers from gh stack view --json, then for each PR:
#   ~/work/ai/repository-helpers/scripts/dev/post-pr-submission-checks --pr <n>
# or: gh pr checks <n>   # repeat every ~5s until all pass or one fails
```
Do **not** mark CI done until **every** submitted PR in the stack is green. If any check fails, inspect logs (`gh run view <run-id> --log-failed`), fix locally, squash/amend on the layer, resubmit, and poll all layers again.

**Step 3 — Verify stack health locally**:
```bash
gh stack view --json
```
Check: correct parent order and expected PRs for branches you touched.

**Step 4 — Verify each PR on GitHub**:
```bash
gh pr view <number> --json number,title,baseRefName,mergeable,mergeStateStatus,files \
  --jq '{number,title,base:.baseRefName,mergeable,mergeStateStatus,files:[.files[].path]}'
```
Check: `mergeable` is `MERGEABLE`, `mergeStateStatus` is `CLEAN` or `BLOCKED` (not `DIRTY` or `CONFLICTING`), base ref is correct, files changed are exactly what you expect.

**Step 5 — Verify PR titles and descriptions match actual content**:
After any branch reorganization, rebase, or restack, review each PR's title and description against its actual diff. Titles and descriptions written before a reorg will be stale. Update them via:
```bash
gh api repos/{owner}/{repo}/pulls/{pr} --method PATCH --field title="..." --field body="..."
```

Do not declare a PR ready until Steps 3, 4, and 5 all pass.

- ✅ All tests passing
- ✅ **90% minimum code coverage** (`uv run pytest --cov=app --cov-fail-under=90`)
- ✅ **Pyright type checking passes** (`uv run pyright`) - enforced by CI/CD
- ✅ **All functions have complete type signatures** (parameters and return types) - enforced by Pyright
- ✅ **Ruff lint and format pass** (`uv run ruff check app config web_ui` and `uv run ruff format --check app config web_ui`)
- ✅ No pytest warnings
- ✅ VS Code Problems panel clear
- ✅ **All test assertions use PyHamcrest** (`assert_that()` — no naked `assert` statements)
- ✅ **CI/CD pipeline passes** (GitHub Actions at `.github/workflows/ci.yml`)
  - Verifies Python 3.14 is used (latest stable)
  - Runs all tests with coverage check
  - **Validates type annotations with Pyright (blocks PR if types missing)**
  - Validates lint and formatting with Ruff
  - Validates shell scripts with shellcheck
  - Checks for pending migrations
**Directory Layout Rules**:
- ❌ **NEVER move** `tsconfig.json`, `tsconfig.test.json`, `eslint.config.mjs`, `pyrightconfig.json`, or `vitest.config.ts` out of the project root — these are discovered by VS Code and IDE tooling by walking up from source files; moving them silently breaks IDE integration (type checking, linting, test discovery).
- ✅ Only move config files that are invoked explicitly by path (e.g., `dev-tooling/esbuild.config.mjs` called via `node dev-tooling/esbuild.config.mjs`). Ruff is configured in `pyproject.toml` under `[tool.ruff]`.
- Rationale: Tool config discovery and IDE integration depend on root-level placement; build script invocations do not.

**Server Management** (scripts from [repository-helpers](https://github.com/the-hcma/repository-helpers)):
- ✅ **Background service**: The server runs as a systemd user service, installed via `~/work/ai/repository-helpers/scripts/setup-service`
- ✅ **Session init**: `~/work/ai/repository-helpers/scripts/dev/start-development --refresh` at the start of each session — syncs and ensures the service is running
- ✅ **Service status**: `~/work/ai/repository-helpers/scripts/setup-service --status`
- ❌ **NEVER start the production server** (`./scripts/my-tracks-server`) during development or testing
- ✅ Tests run using Django's test framework (no server needed)
- ✅ Manual testing should be done by user on their running server
- ❌ Do not run curl/http commands against port 8080 during automated testing
- Rationale: Prevents interference with user's running server, avoids port conflicts

**Test Concurrency**:
- Tests may be run by multiple agents simultaneously (e.g., parallel agent sessions)
- Tests use OS-allocated ports (`port=0`) and isolated databases, so concurrent runs do not conflict
- Rationale: Agents working on different PRs should not have to wait for each other's test suites
**After PR is merged**:
1. Initialize session: `~/work/ai/repository-helpers/scripts/dev/start-development --refresh` — pulls the merged commit, prunes the branch, and restarts the service to pick up changes.
2. Apply any pending migrations: `uv run python manage.py migrate`

**GitHub Actions Polling** (mandatory after every stack submit):
- Do **not** tell the user CI is fixed or the PR is ready until you have seen checks pass on **every** open PR in the stack (or report the specific failure).
- Prefer `~/work/ai/repository-helpers/scripts/dev/post-pr-submission-checks --pr <n>` per layer; or poll `gh pr checks <n>` with short sleeps (5–10 seconds).
- Discover stack PRs with `gh stack view --json` and wait on each number before declaring the stack green.
- On failure, fetch logs (`gh run view <run-id> --log-failed` or job logs via `gh api`), fix, resubmit the stack layer, and poll all layers again.
- Avoid long idle waits (20–30 seconds) between checks.
- Rationale: Faster feedback loop; avoids leaving the user to discover CI failures; keeps PR branches to one amended commit.

### Data Safety Requirements

**CRITICAL - User Data Protection**:
- ❌ **NEVER delete, modify, or purge user data without explicit user approval**
- ❌ **NEVER run destructive database operations** (DELETE, TRUNCATE, DROP) without asking first
- ✅ **ALWAYS ask before**: removing duplicates, cleaning up records, migrating data destructively
- ✅ **ALWAYS offer to create a backup** before any data modification
- If a migration or fix requires data deletion, present the impact to the user first
- Example: "This will delete 93 duplicate records. Should I proceed? Would you like a backup first?"
- Rationale: User data is irreplaceable; err on the side of caution

### Pull Request Requirements

**Single Responsibility Principle**:
- Each PR must address **one single concern** (one feature, one bug fix, one refactor, etc.)
- DO NOT mix unrelated changes in the same PR (e.g., documentation + bug fixes)
- If you discover additional issues while working on a PR, create separate PRs for them

**PR Title and Description**:
- **PR title must accurately reflect the single concern** being addressed
- **PR description must document only changes related to that concern**
- Title and description must always match the actual changes in the PR
- If you realize the PR is addressing multiple concerns, split it into separate PRs

## Agent 1: Implementation Agent

**Model**: `claude-opus-4.6` (see AGENT_MODELS.md)

**Role**: Core developer focused on creating efficient, maintainable code.

**Responsibilities**:
- Design and maintain a self-hosted location tracking backend for the OwnTracks Android/iOS app, persisting geolocation data and providing real-time visualization
- Use modern Python features (3.14+) including type hints and dataclasses where appropriate
- Write clear, self-documenting code with comprehensive docstrings
- Follow PEP 8 style guidelines

**Approach**:
- Use Django REST Framework for API endpoints
- Implement OwnTracks HTTP protocol compatibility
- Create models for devices and location data
- Validate input and raise informative exceptions
- Use type hints for all public APIs
- Use `uv` for dependency management

**Modern Python Typing**:
- Use built-in generic types instead of `typing` module equivalents (Python 3.9+)
- Examples:
  - ✅ `list[str]` instead of ❌ `List[str]`
  - ✅ `dict[str, Any]` instead of ❌ `Dict[str, Any]`
  - ✅ `tuple[str, ...]` instead of ❌ `Tuple[str, ...]`
  - ✅ `set[int]` instead of ❌ `Set[int]`
- Only import from `typing` what you actually need (e.g., `Any`, `cast`, `TypeVar`)
- Rationale: Cleaner code, no unnecessary imports, follows modern Python conventions

**HTTP Status Codes**:
- MUST use `rest_framework.status` constants instead of hardcoded numbers
- Import: `from rest_framework import status`
- Examples:
  - ✅ `status.HTTP_200_OK` instead of ❌ `200`
  - ✅ `status.HTTP_201_CREATED` instead of ❌ `201`
  - ✅ `status.HTTP_400_BAD_REQUEST` instead of ❌ `400`
  - ✅ `status.HTTP_404_NOT_FOUND` instead of ❌ `404`
- Apply to both production code and tests
- Rationale: Self-documenting, type-safe, prevents typos

**Transport Labels in Log Messages**:
- Every client-activity log message MUST begin with a lowercase transport tag in brackets
- Tags identify the protocol and encryption used for the connection:
  - `[mqtt]` — plain MQTT (TCP)
  - `[mqtt-tls]` — MQTT over TLS
  - `[http]` — plain HTTP
  - `[http-tls]` — HTTP over TLS (future)
  - `[ws]` — WebSocket
- Tags are always lowercase, always first, always in brackets
- TLS identity info follows the action, not the tag: `[mqtt-tls] Location saved: id=42, device=hcma (CN=hcma [AD:BF:AA:5C])`
- When broadcasting from one transport to another, the tag reflects the **origin** transport: `[mqtt-tls] Broadcasting location to WebSocket ...`
- **Logging overhead (CRITICAL)**:
  - Avoid **adjacent `logger.*(...)` calls** for the same event — prefer **one log record** with a single formatted message.
  - When you want a traceback, prefer a single call with `exc_info=True` (e.g. `logger.critical("...", exc_info=True)`) instead of `logger.critical(...)` + `logger.exception(...)`.
  - If two adjacent log lines must remain at different levels (e.g. INFO + DEBUG), guard the lower level: `if logger.isEnabledFor(logging.DEBUG): ...` to avoid expensive formatting when disabled.
- Examples:
  - ✅ `[mqtt-tls] Client connected: hcma from 192.168.1.5 (CN=hcma [AD:BF:AA:5C])`
  - ✅ `[mqtt] Client connected: hcma from 192.168.1.5`
  - ✅ `[http] Incoming location request from: 10.0.0.1`
  - ✅ `[ws] Client connected from 192.168.1.5:54321`
  - ❌ `[MQTT] Client connected: hcma from 192.168.1.5 via TLS (CN=...)` (uppercase, verbose)
  - ❌ `WebSocket client connected from 192.168.1.5` (no transport tag)
- Rationale: Consistent, scannable logs; easy to grep by transport; clear origin tracking

**PKI / server TLS identity logs** (not incoming client activity, but same tagging discipline):
- Logs that summarize **which certificates the server is using** MUST still begin with the bracket transport tag that matches the listener:
  - `[mqtt-tls]` — PEM loaded from the DB for the embedded MQTT TLS listener (`_log_cert_info` in `app/apps.py`)
  - `[http-tls]` — HTTPS frontend certificate introspection (`_log_web_cert_info`, e.g. nginx-mounted PEM)
- Prefer structured `key=value` fragments after the tag (single INFO/WARNING record per line) so lines stay grep-friendly and match the rest of the verbose formatter (`%(asctime)s... | LEVEL | module | message`).
- If a log line shows a **truncated timestamp** (missing leading digits) while neighboring lines are fine, treat it as **external corruption or mixed writers** on the log sink — Python emits one full line per record; fix the sink (one writer per file, no shell truncate-in-place on an active log).
- Rationale: Avoids “raw prose” under `apps` that looks unrelated to MQTT/WebSocket traffic; matches operator expectations when grepping `[mqtt-tls]` during TLS incidents.

**Outgoing device MQTT commands (`CommandPublisher`)**:
- All publishes to OwnTracks device command topics (`owntracks/{user}/{device}/cmd`) MUST go through `CommandPublisher.send_command` (or helpers that call it) so logging stays centralized.
- At **INFO**, every outbound command MUST log **once** with action, owner, device, topic, wire byte length, and the full outgoing JSON text. Use `mqtt_payload_json_for_log()` (sorted keys, wire bytes unchanged) for the logged JSON string so logs are stable and easy to compare.
- If you add a new command type or a code path that publishes to `/cmd` without `CommandPublisher`, update `CommandPublisher` or align logging with the same pattern—do not leave silent publishes.
- Rationale: Verifies exactly what phones receive (coordinates, config, etc.) and speeds up debugging when devices disagree with the server.

**Shell Script Convention**:
- All shell scripts MUST be created without the `.sh` extension
- Use hyphens for multi-word script names (kebab-case)
- Examples: `setup` (not `setup.sh`), `my-tracks-server` (not `start_server.sh` or `start_server`)
- Make scripts executable with `chmod +x scriptname`
- Use shebang `#!/usr/bin/env bash` for portability
- **Variable naming**: Use lowercase for local/non-exported variables, UPPERCASE only for exported environment variables
  - ✅ `port=8080` (local variable)
  - ✅ `log_level="WARNING"` (local variable)
  - ✅ `export DJANGO_LOG_LEVEL="$log_level"` (exported to environment)
  - ❌ `PORT=8080` (uppercase for non-exported variable)
- Rationale: Cleaner command-line interface, Unix convention, distinguishes local from exported variables

**Shell Script Logging Convention**:
- Scripts that run services MUST support configurable logging
- Provide `--log-level` flag accepting: debug, info, warning, error, critical
- Default log level: `warning` (balances information with noise reduction)
- Logs MUST go to a file by default (in `logs/` directory)
- Provide `--console` flag to output logs to console instead
- Log files use fixed name: `logs/my-tracks.log` with automatic rotation
- Keep last 5 log files: `my-tracks.log.1` through `my-tracks.log.5`
- Always show log destination on startup
- Examples:
  - ✅ `./scripts/my-tracks-server` (warning level, file logging to logs/my-tracks.log)
  - ✅ `./scripts/my-tracks-server --log-level debug` (debug level, file logging)
  - ✅ `./scripts/my-tracks-server --console` (warning level, console output)
  - ✅ `./scripts/my-tracks-server --log-level info --console` (info level, console output)
- Rationale: Consistent debugging experience, production-ready defaults, preserves logs for analysis, automatic cleanup

**Shell Script Quality**:
- All shell scripts MUST pass shellcheck linting
- shellcheck is MANDATORY - if not installed, test script will automatically install it via brew
- Installation failure blocks the build (test fails if shellcheck cannot be installed)
- Each shell script SHOULD have a corresponding test file (e.g., `test-script-name`)
- Test files must validate:
  - Help message display
  - Invalid argument handling
  - Expected flag behaviors
  - Shellcheck compliance (no longer skipped - auto-installs if missing)
- Run tests before committing: `./test-script-name`
- Rationale: Catches common shell scripting errors, ensures reliability, consistent tooling across environments

**No Python in Infrastructure Shell Scripts**:
- Infrastructure bash scripts MUST NOT invoke `python3` for utility operations (URL parsing, secret generation, encoding, etc.)
- Python may be absent, in a broken venv, or pointing to the wrong interpreter on the target machine — the script would silently fail or require debug knowledge to fix
- Use pure bash built-ins and standard POSIX tools instead:
  - ✅ Pure bash URL parsing (`parse_db_url()` with `${var%%:*}` / `${var#*:}` patterns)
  - ✅ `openssl rand -base64 48` for secret generation (falls back to `/dev/urandom` + `tr`)
  - ✅ `printf '%b'` for `\xHH` decoding (URL percent-decode)
  - ✅ `printf '%%%02X'` for percent-encoding single characters
  - ❌ `python3 -c "import urllib.parse; urllib.parse.quote(...)"`
  - ❌ `python3 -c "import secrets; secrets.token_urlsafe(48)"`
- Rationale: Infrastructure scripts run before the project venv is guaranteed to exist; bash + standard tools are always present

**Python CLI Tools**:
- **MUST use Typer** for command-line argument parsing instead of argparse
- Use `Annotated` types with `typer.Option()` and `typer.Argument()` for clean, type-safe CLIs
- Shebang: `#!/usr/bin/env python3` (standard, portable)
- **MUST include auto-activation via `uv run`** so scripts work without manual venv activation:
  ```python
  # === Auto-activate via uv ===
  import os
  import shutil
  import sys

  def _ensure_uv() -> None:
      """Re-exec under `uv run` if not already in the managed environment."""
      if os.environ.get("UV_ACTIVE") or "/.venv/" in (sys.executable or ""):
          return
      uv = shutil.which("uv")
      if uv:
          os.execv(uv, [uv, "run", sys.argv[0], *sys.argv[1:]])

  _ensure_uv()
  # === End auto-activate ===
  ```
- Use `typer.echo()` for output instead of `print()` for consistent behavior
- Use `raise typer.Exit(code=1)` for error exits instead of `sys.exit()`
- Example structure:
  ```python
  from typing import Annotated, Optional
  import typer

  app = typer.Typer(help="Tool description", add_completion=False)

  @app.command()
  def main(
      name: Annotated[str, typer.Argument(help="Description")],
      verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose output")] = False,
  ) -> None:
      """Command docstring becomes the help text."""
      typer.echo(f"Hello {name}")

  if __name__ == "__main__":
      app()
  ```
- Benefits: Auto-generated help with colors, type validation, shell completion, cleaner code
- Rationale: Modern Python CLI standard, leverages type hints, better developer experience

**Module-Level State**:
- **NEVER use module-level mutable variables** (`global` statements are a code smell)
- Group related mutable state into a holder class (e.g., `_MqttBrokerState`) and expose a single module-level instance
- Holder classes encapsulate state, eliminate `global` declarations, and make patching in tests cleaner
- Example:
  - ❌ `_broker: Any = None`, `_loop = None`, `_thread = None` (3 loose globals + `global` in every function)
  - ✅ `class _BrokerState: broker, loop, thread` → `_state = _BrokerState()` (one instance, zero `global`)
- Rationale: Avoids `global` keyword, groups related state, improves testability

**Error Message Guidelines**:
- Error messages must provide context, not just indicate failure
- Include both what was received and what was expected
- Format: "Expected <type/constraint>, got <actual_value>" or similar
- Example: ✅ "Expected a sequence, got int" ❌ "Invalid input type"
- Example: ✅ "All values must be numeric (int or float), got str" ❌ "must be numeric"

**Code Formatting Standards**:
- **Empty lines MUST NOT contain any whitespace** (no trailing spaces or tabs)
- **Imports MUST be sorted** (Ruff `I` rules / `ruff check --fix`; PEP 8 import ordering)
- Import order: standard library, third-party, local application
- **All imports MUST be at module level** — no local/lazy imports inside functions or methods
  - ✅ `from app.models import Device` at top of file
  - ❌ `from app.models import Device` inside a function body
  - `TYPE_CHECKING` guard imports are acceptable (they are module-level by nature)
  - When moving imports to module level, update test patches to target the importing module (e.g., `patch.object(apps_module, "MQTTBroker", ...)` instead of `patch("app.mqtt.broker.MQTTBroker", ...)`)
  - Rationale: Local imports hide dependencies, complicate patching in tests, and violate PEP 8
- Run `uv run ruff check --fix app config web_ui` and `uv run ruff format app config web_ui` before committing
- Run `find . -name "*.py" -type f -exec sed -i '' 's/^[[:space:]]*$//' {} +` to remove trailing whitespace
- Rationale: Consistent code style, reduces git diff noise, improves readability

**Timezone Handling**:
- **Database MUST store all timestamps in UTC** (`TIME_ZONE = 'UTC'`, `USE_TZ = True`)
- **Display timestamps in local timezone** for logs and web UI
- Use Django's timezone-aware datetime objects (`timezone.now()`, `timezone.make_aware()`)
- Logs: Use `LocalTimeFormatter` to convert UTC to local time in output
- Web UI: Convert Unix timestamps to local time using JavaScript's `Date` object
- API: Return `timestamp_unix` (Unix timestamp) for client-side timezone conversion
- Rationale: Consistent storage in UTC, flexible display in user's timezone, no timezone confusion

**Coordinate Display**:
- Always render lat/lon **display values** in templates with `|floatformat:6` (6 decimal places ≈ 0.1 m precision)
- Do **not** apply `floatformat` to `data-lat`/`data-lon` HTML attributes or values passed to JavaScript — those must retain full precision for map/calculation use
- Applies to all templates: `profile.html`, `geofences.html`, `admin_panel.html`, and any future templates

## Agent 2: Primary Critique Agent (Claude)

**Model**: `claude-opus-4.5` (see AGENT_MODELS.md)

**Role**: Code reviewer ensuring correctness, performance, and quality.

**Responsibilities**:
- Review implementation for algorithmic correctness
- Verify that the exposed webserver endpoints work as expected
- Check edge case handling completeness
- Validate type hints and documentation quality
- Ensure PEP 8 compliance
- Identify potential bugs or performance issues
- Suggest improvements for readability and maintainability
- Enforce consistent nomenclature and naming conventions

**Nomenclature Guidelines**:
- Use descriptive names for mappings that show key→value relationship:
  - ✅ `index_to_value` (clear: index maps to value)
  - ✅ `user_id_to_name` (clear: user ID maps to name)
  - ✅ `user_id_to_attributes` (clear: user ID maps to attributes)
  - ✅ `field_name_to_value` (clear: field name maps to value, e.g., for request data)
- Extract key and value names from context to form `{key}_to_{value}` pattern:
  - ❌ `value_map` → ✅ Identify what the key and value represent (e.g., `device_id_to_location`)
  - ❌ `data_dict` → ✅ Identify what maps to what (e.g., `timestamp_to_reading`)
  - ❌ `request_dict` → ✅ `field_name_to_value` (request data is field names mapping to values)
- Variable names should be self-documenting
- Avoid generic suffixes like `_map`, `_dict` when more specific names are available

**Security Guidelines**:

Passwords must never appear in shell command arguments — they end up in bash history (`~/.bash_history`) and in process listings (`ps aux`). Environment variables like `PGPASSWORD` are safer than argv but still visible to any process that can read `/proc/<pid>/environ` on Linux.

- **In scripts (psql calls)**: use a temporary `.pgpass` file scoped to the call — never `PGPASSWORD`:
  ```bash
  _run_psql() {
      local password="$1"; shift
      local pgpass_file
      pgpass_file="$(mktemp)"
      chmod 0600 "$pgpass_file"
      printf '*:*:*:*:%s\n' "$password" > "$pgpass_file"
      PGPASSFILE="$pgpass_file" PGCONNECT_TIMEOUT=5 psql "$@"
      local rc=$?; rm -f "$pgpass_file"; return $rc
  }
  ```
  - ✅ `_run_psql "$pw" -h host -U user -d db -c "SELECT 1"`
  - ❌ `PGPASSWORD="$pw" psql -h host -U user -d db -c "SELECT 1"` (visible in `/proc/<pid>/environ`)
  - ❌ `psql "postgresql://user:password@host/db" -c "SELECT 1"` (visible in `ps aux`)
- **In user-facing instructions**: use interactive prompts that don't record the password:
  - ✅ `psql -c '\password username'` — prompts interactively, nothing stored
  - ❌ `psql -c "ALTER USER username PASSWORD 'plaintext';"`
- **In manual test commands shown to the user**: use `-W` to force an interactive password prompt
  - ✅ `psql -h localhost -U user -d db -W -c "SELECT 1"` (prompts for password interactively)
  - ❌ `psql "postgresql://user:yourpassword@localhost/db"` (password in URL ends up in history)

**Review Checklist**:
- [ ] Algorithm correctness verified
- [ ] All edge cases properly handled
- [ ] Type hints complete and accurate
- [ ] Docstrings clear and comprehensive
- [ ] No security vulnerabilities — including **no passwords in command-line arguments or `PGPASSWORD` env var** (use `_run_psql` / `.pgpass` temp files — see Security Guidelines above)
- [ ] **No `python3` invocations in infrastructure bash scripts** (use pure bash + `openssl`/`tr`/`printf` — see No Python in Infrastructure Shell Scripts above)
- [ ] Error messages are informative (include both expected and actual values)
- [ ] Naming conventions followed (values, descriptive mappings)
- [ ] No dead code (unused methods, variables, imports, or parameters)
- [ ] **No module-level mutable state** (use holder classes, no `global` keyword)
- [ ] **Transport labels in log messages** (client activity uses `[mqtt]`, `[mqtt-tls]`, `[http]`, `[ws]`; PKI/server cert summaries use `[mqtt-tls]` / `[http-tls]` per PKI / server TLS identity logs above)
- [ ] **Device MQTT commands** (`CommandPublisher`): single INFO log includes full JSON (`mqtt_payload_json_for_log`); new `/cmd` publishes go through `CommandPublisher`
- [ ] **Shell variable naming** (lowercase for all non-exported variables; UPPERCASE only for `export`ed variables passed to subprocesses)
- [ ] **Empty lines have no whitespace** (run `find . -name "*.py" -type f -exec sed -i '' 's/^[[:space:]]*$//' {} +`)
- [ ] **Ruff lint and format pass** (run `uv run ruff check --fix` and `uv run ruff format`)
- [ ] **No local imports** (all imports at module level — no lazy imports inside functions/methods)
- [ ] **Timezone handling correct** (database stores UTC, displays show local time)
- [ ] **VS Code Problems panel is clear** (no import errors, type errors, or linting issues)
- [ ] **Tests run without warnings** (pytest should produce no warnings)
- [ ] **All test assertions use PyHamcrest** (no naked `assert` — use `assert_that()` with matchers)
- [ ] **No hardcoded ports in tests** (use port `0` for OS allocation — never `1883`, `8080`, etc.)
- [ ] **Test mock data matches real-world values** (e.g., `sys.argv` in tests must match actual process invocations, not idealized versions)
- [ ] **CI/CD pipeline passes** (GitHub Actions workflow at `.github/workflows/ci.yml`)

## Agent 2b: Secondary Critique Agent (GPT-5)

**Model**: `gpt-5.1-codex-max` (see AGENT_MODELS.md)

**Role**: Secondary code reviewer providing alternative perspective.

**Responsibilities**:
- Provide independent review from different model perspective
- Look for issues the first critic may have missed
- Focus on practical engineering concerns
- Validate API design and usability
- Check for common anti-patterns
- Assess test coverage completeness
- Suggest alternative approaches when beneficial

**Review Focus**:
- Different reasoning approach may catch different issues
- Cross-validation of the primary critic's findings
- Real-world usability and developer experience
- Code maintainability over time
- Edge cases from a different angle
- Look for dead code (unused methods, setup fixtures that never run, unreachable code)
- **No module-level mutable state** — related state must be grouped into holder classes (no `global` keyword)
- **Transport labels in log messages** — client activity must use `[mqtt]`, `[mqtt-tls]`, `[http]`, `[ws]` tags; MQTT/HTTPS server certificate summaries must use `[mqtt-tls]` / `[http-tls]` as documented under PKI / server TLS identity logs
- **Device MQTT commands** — `CommandPublisher.send_command` logs full outbound JSON in one INFO line; do not bypass for `/cmd` publishes
- **Shell variable naming** — lowercase for all non-exported variables; UPPERCASE only for `export`ed variables
- Error message quality: ensure exceptions provide context with expected vs actual values
- **Verify empty lines have no whitespace** (check for trailing spaces)
- **Verify imports are sorted** (should follow PEP 8 ordering)
- **Verify no local imports** (all imports at module level — no lazy imports inside functions/methods)
- **Verify timezone handling correct** (database stores UTC, displays show local time)
- **Verify VS Code Problems panel is clear** (use `get_errors()` tool)
- **Verify tests run without warnings** (check pytest output for PytestWarnings)
- **Verify all test assertions use PyHamcrest** (no naked `assert` — must use `assert_that()` with matchers)
- **Verify no hardcoded ports in tests** (use port `0` for OS allocation — never `1883`, `8080`, etc.)
- **Verify test mock data matches real-world values** (e.g., `sys.argv` in tests must match actual process invocations, not idealized versions)
- **Verify CI/CD pipeline passes** (check GitHub Actions at `.github/workflows/ci.yml`)

**When to Use**:
- After primary critic review
- For complex algorithmic decisions
- When you want a second opinion
- To validate critical sections of code

## Agent 3: Testing Agent

**Model**: `claude-opus-4.5` (see AGENT_MODELS.md)

**Role**: Quality assurance through comprehensive testing.

**Responsibilities**:
- Write unit tests using pytest framework
- Use PyHamcrest matchers for expressive assertions
- **NEVER use naked `assert` statements** — always use `assert_that()` with PyHamcrest matchers
- Cover all normal use cases with various input sizes
- Verify percentile calculation accuracy against known values
- **Achieve minimum 90% code coverage** (verified with `uv run pytest --cov=app --cov-fail-under=90`)
- Document test scenarios clearly

**Mandatory Testing Approach**:
1. **Traditional Unit Tests**: Cover known scenarios and edge cases
2. **Reference Implementation**: Create a local workload generator to test the endpoints
3. **Randomized Testing**: REQUIRED for every implementation

**Testing Strategy**:
- Use PyHamcrest matchers: `assert_that()`, `equal_to()`, `close_to()`, `raises()`
- **NEVER use naked `assert`** — every assertion must use `assert_that()` with a matcher
- Common matchers: `is_()`, `is_not()`, `none()`, `not_none()`, `instance_of()`, `greater_than()`, `less_than()`, `contains_string()`, `has_item()`, `has_length()`, `has_entries()`, `has_key()`, `any_of()`, `calling().raises()`
- Examples:
  - ✅ `assert_that(result, is_(not_none()))` instead of ❌ `assert result is not None`
  - ✅ `assert_that(value, greater_than(0))` instead of ❌ `assert value > 0`
  - ✅ `assert_that(items, instance_of(list))` instead of ❌ `assert isinstance(items, list)`
  - ✅ `assert_that(text, contains_string("foo"))` instead of ❌ `assert "foo" in text`
  - ✅ `assert_that(flag, is_(True))` instead of ❌ `assert flag`
- Rationale: Consistent assertion style, better error messages on failure, expressive test intent

**No wall-clock timing in tests**:
- Do **not** use real elapsed time (`time.sleep`, `time.monotonic()` deltas, tight `elapsed < N` checks) to prove async or scheduling behavior — it flakes on CI
- Prefer **`time-machine`** for time-based production logic, or **synchronization primitives** (`threading.Event`, gated mock side effects) to prove ordering
- See `.cursor/rules/no-wall-clock-tests.mdc`

**Port Handling in Tests**:
- **NEVER hardcode well-known ports** (`1883`, `8080`, etc.) in test code
- Use port `0` (OS-allocated) for any test that needs a port number
- When port appears in assertions (e.g., log messages), assert against `0` not a well-known port
- Rationale: Avoids port conflicts, tests should never depend on specific port availability

**Mock Data Realism**:
- **Test mock data MUST match real-world values**, not idealized versions
- Before mocking `sys.argv`, CLI arguments, or process state, verify what the real values look like
- Example: daphne's `sys.argv` is `[".venv/bin/daphne", "-b", "0.0.0.0", ...]` — NOT `["daphne", "daphne", ...]`
- Add guard assertions that validate mock data structure (e.g., assert `argv[1]` is a flag, not a binary name)
- Rationale: Prevents tests that confirm buggy assumptions instead of catching real bugs

**Quality Gates**:
- [ ] All traditional unit tests pass
- [ ] **90% minimum code coverage achieved** (run `uv run pytest --cov=app --cov-fail-under=90`)
- [ ] **VS Code Problems panel is clear** (no errors in test files)
- [ ] **Tests run without warnings** (no PytestWarnings or configuration issues)
- [ ] **All test assertions use PyHamcrest** (no naked `assert` — use `assert_that()` with matchers)
- [ ] **No hardcoded ports** (use port `0` — never `1883`, `8080`, etc.)
- [ ] **Mock data matches real-world values** (verify against actual process invocations)
- [ ] **CI/CD pipeline passes** (GitHub Actions workflow at `.github/workflows/ci.yml`)
