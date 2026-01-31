# Agent Definitions

This document defines the four specialized agents for the OwnTracks Django backend project.

**Configuration**: See [AGENT_MODELS.md](./AGENT_MODELS.md) for model assignments and `.agent-models.json` for machine-readable configuration.

**Package Manager**: This project uses `uv` as the Python package manager for fast, reliable dependency management.

## Workflow Requirements

**CRITICAL**: Before creating any pull request, the following workflow MUST be completed:

1. **Implementation Agent** completes the code changes
2. **Primary Critique Agent (Claude)** reviews the implementation
3. **Secondary Critique Agent (GPT-5)** provides independent review
4. **Testing Agent** ensures comprehensive test coverage
5. **Final verification**: All agents confirm VS Code Problems panel is clear

**Only after all review agents have completed their analysis and approved the changes** should a pull request be created. This ensures code quality, correctness, and adherence to project standards before submission.

### Pull Request Requirements

When creating or updating a pull request:
- **PR title must accurately reflect all changes** in the PR
- **PR description must document all changes**, not just the initial ones
- If additional commits are added to a PR branch, review and update the PR title/description to encompass all changes
- Ensure the PR description includes comprehensive review completion status for all changes

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

**Shell Script Convention**:
- All shell scripts MUST be created without the `.sh` extension
- Examples: `setup` (not `setup.sh`), `start_server` (not `start_server.sh`)
- Make scripts executable with `chmod +x scriptname`
- Use shebang `#!/usr/bin/env bash` for portability
- Rationale: Cleaner command-line interface, Unix convention

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
- Achieve 100% code coverage
- Document test scenarios clearly

**Mandatory Testing Approach**:
1. **Traditional Unit Tests**: Cover known scenarios and edge cases
2. **Reference Implementation**: Create a local workload generator to test the endpoints
3. **Randomized Testing**: REQUIRED for every implementation

**Testing Strategy**:
- Use PyHamcrest matchers: `assert_that()`, `equal_to()`, `close_to()`, `raises()`

**Quality Gates**:
- [ ] All traditional unit tests pass
- [ ] 90+% code coverage achieved
- [ ] **VS Code Problems panel is clear** (no errors in test files)
- [ ] **Tests run without warnings** (no PytestWarnings or configuration issues)
- [ ] **CI/CD pipeline passes** (GitHub Actions workflow at `.github/workflows/pr-validation.yml`)
