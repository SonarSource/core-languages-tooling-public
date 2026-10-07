# core-languages-tooling-public

Development tooling for Core Languages & Parsers squad — For artifacts accessible from public repos

## Contents

### GitHub Actions

- **[ruling-diff-comment](ruling-diff-comment)** - Analyzes ruling file changes and posts human-readable summaries on PRs
- **[pvf-comment](pvf-comment)** - Parses `/pvf` activation comments into structured outputs
- **[pvf-trigger](pvf-trigger)** - Dispatches the PVF host workflow on a `/pvf` PR comment
- **[pvf-resolve-latest-validated-master](pvf-resolve-latest-validated-master)** - Finds a validated default-branch baseline with a documented calendar-day fallback
- **[pvf-result-comment](pvf-result-comment)** - Posts the PVF result (dashboard link, or run-logs fallback) on the PR
- **[pvf-notify-slack](pvf-notify-slack)** - Sends PVF alerts through the shared Slack action, with the commits since the baseline
- **[common-actions/slack-notify](common-actions/slack-notify)** - Sends a Slack notification summarizing the failed jobs of the current workflow run (call it from a final `if: failure()` job)
