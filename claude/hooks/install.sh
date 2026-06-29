#!/usr/bin/env bash
# Installs Claude Code hooks for .NET development into ~/.claude.
# Prerequisites: bash, curl, jq

set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/SonarSource/dotnet-tooling-public/master/claude/hooks"
CLAUDE_DIR="${HOME:-$USERPROFILE}/.claude"
HOOKS_DIR="$CLAUDE_DIR/hooks"
SETTINGS="$CLAUDE_DIR/settings.json"
HOOK_CMD="bash \"\$HOME/.claude/hooks/add-bom-to-dotnet.sh\""

echo "Installing Claude Code .NET hooks into $CLAUDE_DIR ..."

mkdir -p "$HOOKS_DIR"

# Download hook script
curl -fsSL "$REPO_RAW/add-bom-to-dotnet.sh" -o "$HOOKS_DIR/add-bom-to-dotnet.sh"
chmod +x "$HOOKS_DIR/add-bom-to-dotnet.sh"
echo "  installed: $HOOKS_DIR/add-bom-to-dotnet.sh"

# Create settings.json if it doesn't exist
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"

# Add Write hook only if not already present
if jq -e '.hooks.PostToolUse // [] | map(select(.matcher == "Write")) | length > 0' "$SETTINGS" > /dev/null 2>&1; then
    echo "  settings.json already has a Write hook — skipped (add manually if needed)"
else
    cp "$SETTINGS" "$SETTINGS.bak"
    tmp=$(mktemp)
    jq --arg cmd "$HOOK_CMD" '
        .hooks |= (. // {}) |
        .hooks.PostToolUse |= (. // []) + [{"matcher": "Write", "hooks": [{"type": "command", "command": $cmd}]}]
    ' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
    echo "  updated: $SETTINGS  (backup: $SETTINGS.bak)"
fi

echo "Done. Restart Claude Code for the hooks to take effect."
