# PVF Notify Merger

Composite action that tells whoever merged a PR that the PVF run of the resulting push to the default
branch found problems. It comments on the merged PR, mentions the merger, lists the regressed and
errored projects and the failed jobs, and links the compared commit range and the dashboard.

It runs as steps inside the caller's job, typically after the validation of a push whose baseline
came from [`pvf-resolve-baseline`](../pvf-resolve-baseline). The caller decides when to notify, e.g.
on a regression, an error or a failed validation.

## Two modes

- **Same-repo (default):** the validation runs in the analyzer repo and comments on its own PR
  using `github.token`.
- **Cross-repo:** a separate dashboard-host repo validates a public analyzer. Pass `repository`
  (the analyzer repo) and a `token` that can comment there.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `merged-sha` | Commit of the push; the PR that merged it is commented on | Yes | |
| `previous-sha` | Commit before the push. When `baseline-sha` differs, the comment says the comparison covers several merges. | No | `''` |
| `baseline-version` | Plugin version used as the baseline | Yes | |
| `baseline-sha` | Commit the baseline was built from. Empty omits the compared range. | No | `''` |
| `candidate-version` | Plugin version that was validated | Yes | |
| `regressed-projects` | Projects with a performance regression. Empty omits the line. | No | `''` |
| `errored-projects` | Projects that failed to benchmark. Empty omits the line. | No | `''` |
| `failed-jobs` | Jobs of the validation that failed. Empty omits the line. | No | `''` |
| `dashboard-url` | Published dashboard URL (the validate job `pages-url`). Empty omits the link. | No | `''` |
| `run-url` | URL to the workflow run logs | No | this run |
| `repository` | `owner/name` of the merged PR's repo. Set to the analyzer repo for cross-repo. | No | current repo |
| `token` | Token with `pull-requests:write` on `repository` | No | `github.token` |

When no merged PR is found for `merged-sha` (e.g. a direct push), the action warns and comments nothing.

## Usage

```yaml
notify_merger:
  needs: [resolve_baseline, validate]
  if: >-
    ${{ !cancelled() && github.event_name == 'push' &&
        (needs.validate.result == 'failure' ||
         needs.validate.outputs.has-regression == 'true' ||
         needs.validate.outputs.has-error == 'true') }}
  runs-on: sonar-xs
  permissions:
    contents: read
    pull-requests: write
  steps:
    - uses: SonarSource/core-languages-tooling-public/pvf-notify-merger@master
      with:
        merged-sha: ${{ github.sha }}
        previous-sha: ${{ github.event.before }}
        baseline-version: ${{ needs.resolve_baseline.outputs.baseline-version }}
        baseline-sha: ${{ needs.resolve_baseline.outputs.baseline-sha }}
        candidate-version: ${{ needs.build.outputs.project-version }}
        regressed-projects: ${{ needs.validate.outputs.has-regression == 'true' && needs.validate.outputs.regressed-projects || '' }}
        errored-projects: ${{ needs.validate.outputs.has-error == 'true' && needs.validate.outputs.errored-projects || '' }}
        failed-jobs: ${{ needs.validate.result == 'failure' && 'validate' || '' }}
        dashboard-url: ${{ needs.validate.outputs.pages-url }}
```

## Requirements

- `gh` CLI on the runner.
- **Same-repo:** the caller job grants `contents: read` and `pull-requests: write`.
- **Cross-repo:** the caller provides a `token` with `pull-requests:write` on `repository`
  (e.g. the `pvf-commenter` Vault token).
