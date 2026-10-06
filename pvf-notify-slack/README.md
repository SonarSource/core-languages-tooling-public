# PVF Notify Slack

Composite action that sends a PVF problem alert with commit and merger attribution. Requires
Python 3 and `gh`, a GitHub token with `contents: read` and `pull-requests: read`, and a Slack
incoming webhook. Credentials are supplied by the caller; this action does not retrieve Vault
secrets. Webhook errors do not print the credential URL or response content.

| Input | Default / purpose |
| --- | --- |
| `repository`, `token` | Caller repository and GitHub token |
| `branch` | Caller repository's default branch |
| `baseline-sha` | Empty; baseline for commit-range attribution |
| `head-sha` | Caller SHA |
| `merger-fallback` | Caller triggering actor |
| `validation-result` | **Required**: `success`, `failure` or `skipped` |
| `baseline-result` | **Required**: baseline resolution job outcome |
| `new-issues`, `lost-issues` | `0`; shown only for completed validation |
| `regressed-projects`, `errored-projects` | Empty; affected project names |
| `dashboard-url`, `run-url` | Empty dashboard; current run URL |
| `slack-webhook` | **Required** incoming webhook URL |
| `slack-channel` | **Required** channel; webhook must support channel overrides |
| `display-name` | `Performance Validation` |

The caller gates the job to regressions, errors, validation failures or skipped validation, and
suppresses duplicate framework notifications. This action sends whenever invoked.

Attribution includes the latest 20 commits in the baseline/head range, newest first, with deduplicated
mergers of associated PRs on `branch`, falling back to commit authors and then `merger-fallback`.
Commit titles are bounded to 200 characters. Range/merger lookup failures warn and still send the
alert; delivery failures fail the action. Slack mentions, formatting and link delimiters in
repository-controlled content are escaped.

```yaml
- uses: SonarSource/core-languages-tooling-public/pvf-notify-slack@master
  with:
    baseline-sha: ${{ needs.resolve_baseline.outputs.baseline-sha }}
    head-sha: ${{ github.sha }}
    validation-result: ${{ needs.validate.result }}
    baseline-result: ${{ needs.resolve_baseline.result }}
    regressed-projects: ${{ needs.validate.outputs.regressed-projects }}
    slack-webhook: ${{ steps.secrets.outputs.slack_webhook }}
    slack-channel: squad-pvf-notifs
```

Run tests: `python3 -m unittest discover -v -s pvf-notify-slack -p 'test_*.py'`.
