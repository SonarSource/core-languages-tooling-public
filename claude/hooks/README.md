# Claude Code Hooks for .NET

[Claude Code](https://claude.ai/code) hooks are shell commands that run automatically in response to tool events. The hooks here improve the Claude Code experience when working in .NET repositories.

## Available hooks

### `add-bom-to-dotnet.sh` — UTF-8 BOM on `.cs` / `.vb` files

Claude Code's `Write` tool does not prepend a UTF-8 BOM when creating files. This hook fires automatically after every `Write` call and restores the BOM on `.cs` and `.vb` files, matching the convention used in SonarSource .NET repositories.

## Installation

**One-liner** (requires `bash`, `curl`, `jq`):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/SonarSource/dotnet-tooling-public/master/claude/hooks/install.sh)
```

**Manual**:

1. Copy `add-bom-to-dotnet.sh` to `~/.claude/hooks/`
2. Add the following to `~/.claude/settings.json`:

```json
"hooks": {
  "PostToolUse": [
    {
      "matcher": "Write",
      "hooks": [
        {
          "type": "command",
          "command": "bash \"$HOME/.claude/hooks/add-bom-to-dotnet.sh\""
        }
      ]
    }
  ]
}
```

3. Restart Claude Code.
