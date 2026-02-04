# Migration Notes

## Shell Script Extension Removal

**Date**: 2026-01-31

### Action Required

The following file needs to be renamed to follow Unix conventions (no `.sh` extension):

- `setup.sh` → `setup`

**How to migrate:**

```bash
# Rename the file
mv setup.sh setup

# Ensure it remains executable
chmod +x setup

# Update any local scripts or documentation that reference setup.sh
```

### Rationale

Following Unix/Linux conventions, executable scripts should not have file extensions. This provides:
- Cleaner command-line interface
- Consistency with system commands
- Implementation detail abstraction
- Better user experience

### Implementation Agent Directive

All future shell scripts MUST be created without the `.sh` extension:
- ✅ `setup`, `my-tracks-server`, `backup-owntracks`
- ❌ `setup.sh`, `my-tracks-server.sh`, `backup-owntracks.sh`

Requirements:
- Use `#!/usr/bin/env bash` shebang for portability
- Make executable with `chmod +x scriptname`
- No file extensions

See [AGENTS.md](AGENTS.md) for the full directive.
