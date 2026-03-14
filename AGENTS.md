# Agent Definitions

This document defines the four specialized agents for the My Tracks project.

**Configuration**: See [AGENT_MODELS.md](./AGENT_MODELS.md) for model assignments and `.agent-models.json` for machine-readable configuration.

**Package Manager**: This project uses `uv` as the Python package manager for fast, reliable dependency management.

**Python Version Policy**: Always use the latest stable Python version available via Homebrew. Currently Python 3.14.x is the latest stable release. The project requires Python 3.14+ (`requires-python = ">=3.14"` in pyproject.toml).

## Workflow Requirements

**CRITICAL**: All changes MUST go through pull requests - direct pushes to main are blocked by branch protection.

**Before creating any pull request**, the following workflow MUST be completed:

1. **Implementation Agent** completes the code changes
2. **Primary Critique Agent (Claude)** reviews the implementation
3. **Secondary Critique Agent (GPT-5)** provides independent review
4. **Testing Agent** ensures comprehensive test coverage
5. **Final verification**: All agents confirm VS Code Problems panel is clear
6. **Coverage verification**: Run `uv run pytest --cov=my_tracks --cov-fail-under=90` and ensure it passes
7. **Create feature branch**: NEVER commit or push to main - always create a feature branch

**Pull Request Workflow** (CRITICAL):

1. **Create PR**: Once all pre-PR quality gates pass, create the pull request
2. **Wait for CI/CD**: Poll GitHub Actions frequently (every 5 seconds) until all checks pass
3. **User Testing**: After CI passes, inform user that PR is ready for manual testing
4. **User Approval**: Wait for explicit user approval before proceeding
5. **Submit to merge queue**: Only after user approval, add the `merge-it` label to submit the PR to the Graphite merge queue: `gh pr edit <pr-number> --add-label "merge-it"`
6. **Cleanup**: After merge completes, `gt sync --force` to update local main and clean up branches

**DO NOT**:
- ❌ Create PR before all quality gates pass
- ❌ Ask user to test before CI/CD passes
- ❌ Merge PR without explicit user approval
- ❌ Skip waiting for CI/CD checks
- ❌ **NEVER merge PRs directly** (`gh pr merge`, GitHub merge button, etc.) — always use the `merge-it` label to submit to the merge queue

**Branch Workflow** (CRITICAL - Use Graphite CLI):
- ✅ **ALWAYS** use Graphite CLI for branch and PR management
- ✅ **ALWAYS** use non-interactive mode flags to prevent terminal hangs:
  - `gt create --all --message "msg"` (not `-am`, use full flags)
  - `gt submit --no-interactive --publish` (prevents prompts, publishes as ready-for-review)
  - `gt modify --all --message "msg"` (amend commits non-interactively)
  - `gt sync --force` (sync without prompts)
- ✅ **Create branches**: `gt create --all --message "descriptive commit message"`
- ✅ **Submit PRs** (two steps — both required):
  1. `gt submit --no-interactive --publish` — pushes branch and creates ready-for-review PR (`--publish` is on `gt submit`, not `gt create`)
  2. Fill description: `gh api repos/{owner}/{repo}/pulls/{pr} --method PATCH --field body="..."` (no `--body` flag exists on `gt submit`)
- ✅ **Amend commits**: `gt modify --all --message "updated message"`
- ✅ **View stack**: `gt log short` to see current PR stack
- ✅ **Sync with remote**: `gt sync --force` to update local branches
- ✅ **Prune stale branches**: Periodically run `gt fetch --prune && git branch -vv | grep ': gone]' | awk '{print $1}' | xargs -r git branch -D`
- ❌ **NEVER** use raw git commands for PR workflow (use `gt` instead)
- ❌ **NEVER** commit directly to main
- ❌ **NEVER** push directly to main
- ❌ **NEVER** use interactive gt commands (always add `--no-interactive` or use explicit flags)
- ❌ **NEVER** add `Co-Authored-By: Claude` (or any AI attribution) to commit messages or PR descriptions
- Rationale: Graphite enables clean PR stacking, better code review, consistent workflow. Non-interactive mode prevents terminal hangs in automated environments. `--publish` belongs on `gt submit`, not `gt create`.

**Branch Cleanup**:
- Periodically prune stale remote-tracking branches: `gt fetch --prune`
- Delete local branches whose upstream is gone: `git branch -vv | grep ': gone]' | awk '{print $1}' | xargs -r git branch -D`
- `graphite-base/{pr}` branches are auto-deleted on PR merge (via GitHub Actions)
- Stale `graphite-base/*` branches are cleaned up daily by scheduled workflow
- Graphite auto-cleans merged branches during `gt submit` when it detects merged PRs
- Run cleanup after merging PRs or when branch list becomes cluttered
- Rationale: Keeps repository clean, avoids confusion from old branches

**Pre-PR Quality Gates** — complete ALL steps in order before considering a PR ready:

**Step 1 — Local checks** (catch issues before pushing):
```bash
uv run pyright                                      # type errors
uv run isort --check-only --diff my_tracks config   # import order
uv run flake8 my_tracks config                      # PEP 8 + unused imports/vars
uv run pytest --cov=my_tracks --cov-fail-under=90   # tests + coverage
```
Do not proceed if any of these fail. Fix first.

**Step 2 — Submit via Graphite** (pushes branches and updates PRs):
```bash
GRAPHITE_PROFILE=thehcma gt submit --no-interactive --publish
```

**Step 3 — Verify stack health locally**:
```bash
GRAPHITE_PROFILE=thehcma gt log short
```
Check: correct parent order, no "needs restack", no diverged branch warnings for branches you touched.

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
- ✅ **90% minimum code coverage** (`uv run pytest --cov=my_tracks --cov-fail-under=90`)
- ✅ **Pyright type checking passes** (`uv run pyright`) - enforced by CI/CD
- ✅ **All functions have complete type signatures** (parameters and return types) - enforced by Pyright
- ✅ **Imports sorted with isort** (`uv run isort --check-only my_tracks config`)
- ✅ No pytest warnings
- ✅ VS Code Problems panel clear
- ✅ **All test assertions use PyHamcrest** (`assert_that()` — no naked `assert` statements)
- ✅ **CI/CD pipeline passes** (GitHub Actions at `.github/workflows/pr-validation.yml`)
  - Verifies Python 3.14 is used (latest stable)
  - Runs all tests with coverage check
  - **Validates type annotations with Pyright (blocks PR if types missing)**
  - Validates import sorting with isort
  - Validates shell scripts with shellcheck
  - Checks for pending migrations
**Server Management**:
- ❌ **NEVER start the production server** (`./my-tracks-server`) during development or testing
- ✅ Tests run using Django's test framework (no server needed)
- ✅ Manual testing should be done by user on their running server
- ❌ Do not run curl/http commands against port 8080 during automated testing
- Rationale: Prevents interference with user's running server, avoids port conflicts
**After PR is merged**:
1. Sync with remote: `gt sync --force`
2. Apply any pending migrations: `uv run python manage.py migrate`
3. Restart the server: `./my-tracks-server`

**GitHub Actions Polling**:
- When checking CI/CD status, poll frequently to minimize wait time
- Use short initial delay (5-10 seconds) then check every 5 seconds
- Example: `sleep 10 && gh pr checks <pr-number>` then `sleep 5 && gh pr checks <pr-number>`
- Avoid long waits (20-30 seconds) between checks
- Rationale: Faster feedback loop, better user experience

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
- Examples:
  - ✅ `[mqtt-tls] Client connected: hcma from 192.168.1.5 (CN=hcma [AD:BF:AA:5C])`
  - ✅ `[mqtt] Client connected: hcma from 192.168.1.5`
  - ✅ `[http] Incoming location request from: 10.0.0.1`
  - ✅ `[ws] Client connected from 192.168.1.5:54321`
  - ❌ `[MQTT] Client connected: hcma from 192.168.1.5 via TLS (CN=...)` (uppercase, verbose)
  - ❌ `WebSocket client connected from 192.168.1.5` (no transport tag)
- Rationale: Consistent, scannable logs; easy to grep by transport; clear origin tracking

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
  - ✅ `./my-tracks-server` (warning level, file logging to logs/my-tracks.log)
  - ✅ `./my-tracks-server --log-level debug` (debug level, file logging)
  - ✅ `./my-tracks-server --console` (warning level, console output)
  - ✅ `./my-tracks-server --log-level info --console` (info level, console output)
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
- **Imports MUST be sorted** using isort (PEP 8 import ordering)
- Import order: standard library, third-party, local application
- **All imports MUST be at module level** — no local/lazy imports inside functions or methods
  - ✅ `from my_tracks.models import Device` at top of file
  - ❌ `from my_tracks.models import Device` inside a function body
  - `TYPE_CHECKING` guard imports are acceptable (they are module-level by nature)
  - When moving imports to module level, update test patches to target the importing module (e.g., `patch.object(apps_module, "MQTTBroker", ...)` instead of `patch("my_tracks.mqtt.broker.MQTTBroker", ...)`)
  - Rationale: Local imports hide dependencies, complicate patching in tests, and violate PEP 8
- Run `isort .` to automatically sort imports before committing
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

**Review Checklist**:
- [ ] Algorithm correctness verified
- [ ] All edge cases properly handled
- [ ] Type hints complete and accurate
- [ ] Docstrings clear and comprehensive
- [ ] No security vulnerabilities
- [ ] Error messages are informative (include both expected and actual values)
- [ ] Naming conventions followed (values, descriptive mappings)
- [ ] No dead code (unused methods, variables, imports, or parameters)
- [ ] **No module-level mutable state** (use holder classes, no `global` keyword)
- [ ] **Transport labels in log messages** (client activity uses `[mqtt]`, `[mqtt-tls]`, `[http]`, `[ws]`)
- [ ] **Shell variable naming** (lowercase for all non-exported variables; UPPERCASE only for `export`ed variables passed to subprocesses)
- [ ] **Empty lines have no whitespace** (run `find . -name "*.py" -type f -exec sed -i '' 's/^[[:space:]]*$//' {} +`)
- [ ] **Imports are sorted** (run `isort .` to fix)
- [ ] **No local imports** (all imports at module level — no lazy imports inside functions/methods)
- [ ] **Timezone handling correct** (database stores UTC, displays show local time)
- [ ] **VS Code Problems panel is clear** (no import errors, type errors, or linting issues)
- [ ] **Tests run without warnings** (pytest should produce no warnings)
- [ ] **All test assertions use PyHamcrest** (no naked `assert` — use `assert_that()` with matchers)
- [ ] **No hardcoded ports in tests** (use port `0` for OS allocation — never `1883`, `8080`, etc.)
- [ ] **Test mock data matches real-world values** (e.g., `sys.argv` in tests must match actual process invocations, not idealized versions)
- [ ] **CI/CD pipeline passes** (GitHub Actions workflow at `.github/workflows/pr-validation.yml`)

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
- **Transport labels in log messages** — client activity must use `[mqtt]`, `[mqtt-tls]`, `[http]`, `[ws]` tags
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
- **Verify CI/CD pipeline passes** (check GitHub Actions at `.github/workflows/pr-validation.yml`)

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
- **Achieve minimum 90% code coverage** (verified with `uv run pytest --cov=my_tracks --cov-fail-under=90`)
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
- [ ] **90% minimum code coverage achieved** (run `uv run pytest --cov=my_tracks --cov-fail-under=90`)
- [ ] **VS Code Problems panel is clear** (no errors in test files)
- [ ] **Tests run without warnings** (no PytestWarnings or configuration issues)
- [ ] **All test assertions use PyHamcrest** (no naked `assert` — use `assert_that()` with matchers)
- [ ] **No hardcoded ports** (use port `0` — never `1883`, `8080`, etc.)
- [ ] **Mock data matches real-world values** (verify against actual process invocations)
- [ ] **CI/CD pipeline passes** (GitHub Actions workflow at `.github/workflows/pr-validation.yml`)
