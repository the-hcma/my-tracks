# Agent Model Configuration

This file acts as the single source of truth for which AI models are assigned to which agent roles.

## Model Assignments

| Agent Role | Model ID | Provider | Notes |
|------------|----------|----------|-------|
| **Implementation Agent** | `claude-opus-4.6` | Anthropic | Primary coding agent |
| **Primary Critique Agent** | `claude-opus-4.5` | Anthropic | Initial code review |
| **Secondary Critique Agent** | `gpt-5.1-codex-max` | OpenAI | Deep logic/security review |
| **Testing Agent** | `claude-opus-4.5` | Anthropic | Test generation |

## Model Capabilities

- **Claude Opus 4.5**: Excellent at architectural reasoning, Python idioms, and documentation.
- **GPT-5.1 Codex Max**: Specialized in complex logic verification, edge case detection, and security auditing.

## Configuration Updates

To update the model used by an agent, edit the "Model ID" column in the table above.
Also update the `.agent-models.json` file for machine-readable configuration.
