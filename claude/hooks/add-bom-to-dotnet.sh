#!/usr/bin/env bash
# PostToolUse hook: ensure UTF-8 BOM on .cs/.vb files written by the Write tool.
# The Write tool strips the BOM; this restores it automatically.

input=$(cat)
file=$(echo "$input" | jq -r '.tool_input.file_path // empty')

# Only act on .cs and .vb files
[[ "$file" == *.cs || "$file" == *.vb ]] || exit 0

# Guard: file must exist and be a regular file
[[ -f "$file" ]] || exit 0

# Nothing to do if BOM already present (EF BB BF)
if head -c 3 "$file" | od -An -tx1 | grep -q "ef bb bf"; then
    exit 0
fi

# Prepend BOM atomically via a temp file in the same directory
tmp=$(mktemp "$(dirname "$file")/.bom_XXXXXX")
trap 'rm -f "$tmp"' EXIT
printf '\xef\xbb\xbf' > "$tmp"
cat "$file" >> "$tmp"
chmod --reference="$file" "$tmp" 2>/dev/null || true
mv "$tmp" "$file"
