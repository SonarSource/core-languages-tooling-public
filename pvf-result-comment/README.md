# PVF Result Comment

Composite action that posts Performance Validation results to an explicit PR or discovers a
merged PR associated with a commit. Supports same-repo and cross-repo callers. Requires Python 3
and `gh`; the supplied token needs `pull-requests: write`, plus `contents: read` for commit lookup.
The caller controls job conditions, including cancellation behavior.

| Input | Default / purpose |
| --- | --- |
| `pr-number` | Empty; explicit PR number takes precedence over commit lookup |
| `repository`, `token` | Caller repository and GitHub token; override for cross-repo comments |
| `dashboard-url` | Empty; published dashboard URL |
| `new-issues`, `lost-issues` | `0` |
| `run-url` | Current workflow run URL |
| `validation-result` | Empty preserves the original dashboard/fallback formatting; otherwise `success`, `failure`, `skipped` or `cancelled` |
| `commit-sha` | Empty; required when `pr-number` is omitted |
| `branch` | Empty; optional merged-PR base branch filter and commit display label |
| `skip-reason` | `No baseline could be resolved.` |
| `regressed-projects`, `errored-projects` | Empty; affected project names |

Commit lookup chooses the first merged associated PR matching `branch`, when provided. No merged
PR emits a warning and skips posting; API failures fail the action. Failure/skip/cancellation
messages omit issue counts rather than presenting a false clean pass. Rich comments include run
logs even when a dashboard exists. Repository-controlled text and link delimiters are escaped.

Existing callers supplying `pr-number` and no `validation-result` retain their original output.
For cross-repo callers, leave `branch` empty or explicitly supply the analyzer's branch.

```yaml
- uses: SonarSource/core-languages-tooling-public/pvf-result-comment@master
  with:
    pr-number: ${{ inputs.pr-number }}
    commit-sha: ${{ inputs.notify-sha }}
    branch: ${{ github.event.repository.default_branch }}
    validation-result: ${{ needs.validate.result }}
    dashboard-url: ${{ needs.validate.outputs.pages-url }}
    new-issues: ${{ needs.validate.outputs.new-issues }}
    lost-issues: ${{ needs.validate.outputs.lost-issues }}
```

Run tests: `python3 -m unittest discover -v -s pvf-result-comment -p 'test_*.py'`.
