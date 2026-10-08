# PVF Notify Slack

Send a PVF problem alert listing the commits since the baseline. `notify.py` builds the message;
delivery uses
[release-github-actions/slack-message](https://github.com/SonarSource/release-github-actions/tree/master/slack-message),
which converts Markdown to Slack formatting and retrieves the Slack bot token from Vault.

Requires Python 3, `gh`, a GitHub token with `contents: read`, and the caller's normal Vault
authentication setup. Supply the channel without `#`.

| Input | Default / purpose |
| --- | --- |
| `repository`, `token` | Caller repository and GitHub token |
| `branch` | Caller repository's default branch; shown in the alert |
| `baseline-sha` | Empty; baseline for the commit list, omitted when empty |
| `head-sha` | Caller SHA |
| `validation-result` | **Required**: `success`, `failure` or `skipped` |
| `baseline-result` | **Required**: baseline resolution job outcome |
| `new-issues`, `lost-issues` | `0`; shown only for completed validation |
| `regressed-projects`, `errored-projects` | Empty; affected project names |
| `dashboard-url`, `run-url` | Empty dashboard; current run URL |
| `slack-channel` | **Required** destination channel without `#` |

The caller gates the job to regressions, errors, validation failures or skipped validation. This
action sends whenever invoked. Pass the resolver's `baseline-sha` so a skip caused by a missing
baseline can be told apart from other reasons.

The alert lists up to 20 commits (newest first, with author) between baseline and head, and links
the full range when there are more. Commit titles are limited to 200 characters. A failed lookup
warns and still sends the alert; delivery failures fail the action. Repository-controlled text
cannot create Slack mentions or formatting; Slack syntax characters are shown as lookalikes.

```yaml
- uses: SonarSource/core-languages-tooling-public/pvf-notify-slack@master
  with:
    baseline-sha: ${{ needs.resolve_latest_validated_master.outputs.baseline-sha }}
    validation-result: ${{ needs.validate.result }}
    baseline-result: ${{ needs.resolve_latest_validated_master.result }}
    regressed-projects: ${{ needs.validate.outputs.regressed-projects }}
    slack-channel: squad-pvf-notifs
```

Run tests: `python3 -m unittest discover -v -s pvf-notify-slack -p 'test_*.py'`.
