# Agent Definitions

This document defines the four specialized agents for the OwnTracks Django backend project.

**Configuration**: See [AGENT_MODELS.md](./AGENT_MODELS.md) for model assignments and `.agent-models.json` for machine-readable configuration.

**Package Manager**: This project uses `uv` as the Python package manager for fast, reliable dependency management.

**Python Version Policy**: Always use the latest stable Python version available via Homebrew. Currently Python 3.14.x is the latest stable release. The project requires Python 3.12+ as minimum, but should be developed and tested with the latest version to ensure compatibility and access to latest features.

## Workflow Requirements

**CRITICAL**: All changes MUST go through pull requests - direct pushes to main are blocked by branch protection.

**Before creating any pull request**, the following workflow MUST be completed:

1. **Implementation Agent** completes the code changes
2. **Primary Critique Agent (Claude)** reviews the implementation
3. **Secondary Critique Agent (GPT-5)** provides independent review
4. **Testing Agent** ensures comprehensive test coverage
5. **Final verification**: All agents confirm VS Code Problems panel is clear
6. **Coverage verification**: Run `uv run pytest --cov=tracker --cov-fail-under=90` and ensure it passes
7. **Create feature branch**: NEVER commit or push to main - always create a feature branch

**Pull Request Workflow** (CRITICAL):

1. **Create PR**: Once all pre-PR quality gates pass, create the pull request
2. **Wait for CI/CD**: Poll GitHub Actions frequently (every 5 seconds) until all checks pass
3. **User Testing**: After CI passes, inform user that PR is ready for manual testing
4. **User Approval**: Wait for explicit user approval before proceeding
5. **Merge PR**: Only after user approval, merge the PR using squash method
6. **Cleanup**: Delete feature branch and update local main

**DO NOT**:
- ❌ Create PR before all quality gates pass
- ❌ Ask user to test before CI/CD passes
- ❌ Merge PR without explicit user approval
- ❌ Skip waiting for CI/CD checks

**Branch Workflow** (CRITICAL):
- ✅ **ALWAYS** create a feature branch for changes: `git checkout -b feature/description`
- ✅ **ALWAYS** push feature branch: `git push -u origin feature/branch-name`
- ✅ **ALWAYS** create PR from feature branch to main
- ❌ **NEVER** commit directly to main
- ❌ **NEVER** push directly to main
- ❌ **NEVER** attempt `git push origin main`
- Rationale: Branch protection requires all changes via PR, enables code review, prevents accidental breaking changes

**Pre-PR Quality Gates** (all must pass):
- ✅ All tests passing
- ✅ **90% minimum code coverage** (`uv run pytest --cov=tracker --cov-fail-under=90`)
- ✅ No pytest warnings
- ✅ VS Code Problems panel clear
- ✅ **CI/CD pipeline passes** (GitHub Actions at `.github/workflows/pr-validation.yml`)
  - Verifies Python 3.14 is used (latest stable)
  - Runs all tests with coverage check
  - Validates shell scripts with shellcheck
  - Checks for pending migrations

**After PR is merged**:
1. Switch to main branch: `git checkout main`
2. Pull latest changes: `git pull origin main`
3. Apply any pending migrations: `uv run python manage.py migrate`
4. Restart the server: `./start-server`

**GitHub Actions Polling**:
- When checking CI/CD status, poll frequently to minimize wait time
- Use short initial delay (5-10 seconds) then check every 5 seconds
- Example: `sleep 10 && gh pr checks <pr-number>` then `sleep 5 && gh pr checks <pr-number>`
- Avoid long waits (20-30 seconds) between checks
- Rationale: Faster feedback loop, better user experience

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

**Model**: `claude-sonnet-4.5` (see AGENT_MODELS.md)

**Role**: Core developer focused on creating efficient, maintainable code.

**Responsibilities**:
- Design a webserver using Python's django to function as a backend server for  the Android OwnTracks app, it should be able to persist the geolocation information
- Use modern Python features (3.12+) including type hints and dataclasses where appropriate
- Write clear, self-documenting code with comprehensive docstrings
- Follow PEP 8 style guidelines

**Approach**:
- Use Django REST Framework for API endpoints
- Implement OwnTracks HTTP protocol compatibility
- Create models for devices and location data
- Validate input and raise informative exceptions
- Use type hints for all public APIs
- Use `uv` for dependency management

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

**Shell Script Convention**:
- All shell scripts MUST be created without the `.sh` extension
- Use hyphens for multi-word script names (kebab-case)
- Examples: `setup` (not `setup.sh`), `start-server` (not `start_server.sh` or `start_server`)
- Make scripts executable with `chmod +x scriptname`
- Use shebang `#!/usr/bin/env bash` for portability
- Rationale: Cleaner command-line interface, Unix convention

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
  - ✅ `./start-server` (warning level, file logging to logs/my-tracks.log)
  - ✅ `./start-server --log-level debug` (debug level, file logging)
  - ✅ `./start-server --console` (warning level, console output)
  - ✅ `./start-server --log-level info --console` (info level, console output)
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

**Error Message Guidelines**:
- Error messages must provide context, not just indicate failure
- Include both what was received and what was expected
- Format: "Expected <type/constraint>, got <actual_value>" or similar
- Example: ✅ "Expected a sequence, got int" ❌ "Invalid input type"
- Example: ✅ "All values must be numeric (int or float), got str" ❌ "must be numeric"

## Agent 2: Critique Agent (Claude)

**Model**: `claude-sonnet-4.5` (see AGENT_MODELS.md)

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
  - ❌ `value_map` (unclear: what's the key? what's the value?)
  - ❌ `data_dict` (unclear: what maps to what?)
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
- [ ] **VS Code Problems panel is clear** (no import errors, type errors, or linting issues)
- [ ] **Tests run without warnings** (pytest should produce no warnings)
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
- Error message quality: ensure exceptions provide context with expected vs actual values
- **Verify VS Code Problems panel is clear** (use `get_errors()` tool)
- **Verify tests run without warnings** (check pytest output for PytestWarnings)
- **Verify CI/CD pipeline passes** (check GitHub Actions at `.github/workflows/pr-validation.yml`)

**When to Use**:
- After primary critic review
- For complex algorithmic decisions
- When you want a second opinion
- To validate critical sections of code

## Agent 3: Testing Agent

**Model**: `claude-sonnet-4.5` (see AGENT_MODELS.md)

**Role**: Quality assurance through comprehensive testing.

**Responsibilities**:
- Write unit tests using pytest framework
- Use PyHamcrest matchers for expressive assertions
- Cover all normal use cases with various input sizes
- Verify percentile calculation accuracy against known values
- **Achieve minimum 90% code coverage** (verified with `uv run pytest --cov=tracker --cov-fail-under=90`)
- Document test scenarios clearly

**Mandatory Testing Approach**:
1. **Traditional Unit Tests**: Cover known scenarios and edge cases
2. **Reference Implementation**: Create a local workload generator to test the endpoints
3. **Randomized Testing**: REQUIRED for every implementation

**Testing Strategy**:
- Use PyHamcrest matchers: `assert_that()`, `equal_to()`, `close_to()`, `raises()`

**Quality Gates**:
- [ ] All traditional unit tests pass
- [ ] **90% minimum code coverage achieved** (run `uv run pytest --cov=tracker --cov-fail-under=90`)
- [ ] **VS Code Problems panel is clear** (no errors in test files)
- [ ] **Tests run without warnings** (no PytestWarnings or configuration issues)
- [ ] **CI/CD pipeline passes** (GitHub Actions workflow at `.github/workflows/pr-validation.yml`)
