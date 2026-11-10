# core-languages-tooling-public

Development tooling for the Analysis Platform squad — For artifacts accessible from public repos

## Contents

### GitHub Actions

- **[ruling-diff-comment](ruling-diff-comment)** - Analyzes ruling file changes and posts human-readable summaries on PRs
- **[pvf-comment](pvf-comment)** - Parses `/pvf` activation comments into structured outputs
- **[pvf-trigger](pvf-trigger)** - Dispatches the PVF host workflow on a `/pvf` PR comment
- **[pvf-result-comment](pvf-result-comment)** - Posts the PVF result (dashboard link, or run-logs fallback) on the PR
- **[pvf-resolve-baseline](pvf-resolve-baseline)** - Resolves the PVF baseline of a push to the default branch from the previous commit's build
- **[pvf-notify-merger](pvf-notify-merger)** - Comments on the merged PR when the PVF run of its push found problems
- **[common-actions/slack-notify](common-actions/slack-notify)** - Sends a Slack notification summarizing the failed jobs of the current workflow run (call it from a final `if: failure()` job)

### Local Tools

- **[ruling-diff-comment](ruling-diff-comment#previewing-real-ruling-changes-locally)** - Previews ruling JSON and SARIF diff comments from an analyzer checkout without GitHub credentials
- **[ruling_diff_enhancer](ruling-diff-comment/ruling_diff_enhancer)** - Uses local rule metadata and the OpenAI client through Portkey to triage ruling diff examples
