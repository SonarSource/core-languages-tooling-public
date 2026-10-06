# core-languages-tooling-public

Development tooling for Core Languages & Parsers squad — For artifacts accessible from public repos

## Contents

### GitHub Actions

- **[ruling-diff-comment](ruling-diff-comment)** - Analyzes ruling file changes and posts human-readable summaries on PRs
- **[pvf-comment](pvf-comment)** - Parses `/pvf` activation comments into structured outputs
- **[pvf-trigger](pvf-trigger)** - Dispatches the PVF host workflow on a `/pvf` PR comment
- **[pvf-resolve-baseline](pvf-resolve-baseline)** - Resolves a deployed baseline from validated or previous build artifacts
- **[pvf-result-comment](pvf-result-comment)** - Posts PVF results on an explicit PR or the merged PR associated with a commit
- **[pvf-notify-slack](pvf-notify-slack)** - Sends PVF alerts with bounded commit and merger attribution
- **[common-actions/slack-notify](common-actions/slack-notify)** - Sends a Slack notification summarizing the failed jobs of the current workflow run (call it from a final `if: failure()` job)
