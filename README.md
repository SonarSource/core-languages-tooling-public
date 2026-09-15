# core-languages-tooling-public

Development tooling for Core Languages & Parsers squad — For artifacts accessible from public repos

## Contents

### GitHub Actions

- **[ruling-diff-comment](ruling-diff-comment)** - Analyzes ruling file changes and posts human-readable summaries on PRs
- **[common-actions/slack-notify](common-actions/slack-notify)** - Sends a Slack notification summarizing failed check runs for a GitHub check_suite
- **[common-actions/docs-only-changes](common-actions/docs-only-changes)** - Detects documentation-only changes so callers can skip the full CI pipeline
- **[common-actions/required-checks-gate](common-actions/required-checks-gate)** - Always-reporting gate job so a path-filtered, skipped run never leaves a required check pending
