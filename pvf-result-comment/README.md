# PVF Result Comment

Composite action that posts the **Performance Validation** result back onto a PR.

It runs as steps inside the caller's job. It is the output side of the PVF chain
— [`pvf-trigger`](../pvf-trigger) dispatches the host workflow. This action comments its result once the run completes.

## Two modes

- **Same-repo (default):** the host workflow lives in the caller repo and comments on its own PR
  using `github.token`. Uses every default; only `pr-number` and the result values are required.
- **Cross-repo:** Pass `repository` (the analyzer repo) and a `token` that
  can comment there.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `pr-number` | Pull request number to comment on | Yes | |
| `repository` | `owner/name` of the repo whose PR to comment on. Set to the analyzer repo for cross-repo. | No | current repo |
| `dashboard-url` | Published dashboard URL (the validate job `pages-url`). Empty ⇒ posts the no-dashboard fallback comment. | No | `''` |
| `new-issues` | Number of new issues found | No | `0` |
| `lost-issues` | Number of lost issues | No | `0` |
| `run-url` | URL to the workflow run logs (used in the fallback comment). | No | this run |
| `token` | Token with `pull-requests:write` on `repository`. For cross-repo, pass a token that can comment on the analyzer repo. | No | `github.token` |

## Requirements

- `gh` CLI on the runner (pre-installed on GitHub-hosted runners).
- **Same-repo:** the caller job grants `pull-requests: write`.
- **Cross-repo:** the caller job grants `id-token: write` and provides a `token` with
  `pull-requests:write` on `repository` (e.g. the `pvf-commenter` Vault token).
