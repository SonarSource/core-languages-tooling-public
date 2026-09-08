# PVF Trigger

Composite action that, on a `/pvf` PR comment, resolves the candidate plugin version from the
latest **Build** run and dispatches the host workflow (`performance-validation.yml` by default).

It is a composite action (not a reusable workflow) on purpose: it runs as steps inside the caller's
job, so it adds no workflow-nesting level and does not consume the GitHub 4-level reusable-workflow
budget already used by the PVF framework chain.

Internally it calls the [`pvf-comment`](../pvf-comment) parser action. When a `/pvf` command is found
it invokes the host workflow (`performance-validation.yml` by default) in the target-repo (caller by default).

## Two modes

- **Same-repo (default):** the host workflow (`performance-validation.yml` by default) lives in the
  caller repo and publishes to the caller's own GitHub Pages.
- **Cross-repo:** a **public** analyzer repo dispatches into a separate dashboard-host repo.
  The dashboard-host runs the  benchmark and publishes to its Pages. 
  Set `target-repo`, `target-ref` and `dispatch-token`, plus `target-workflow` when the host
  workflow is not `performance-validation.yml`.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `comment` | Comment body to scan for a `/pvf` command | Yes | |
| `pr-number` | Pull request number the comment was posted on | Yes | |
| `build-workflow` | Filename of the build workflow that uploads the `candidate-version` artifact | No | `build.yml` |
| `rule-prefixes` | Space-separated rule-key prefixes passed to the parser | No | `S` |
| `target-repo` | `owner/name` of the repo hosting the host workflow (`performance-validation.yml` by default). Cross-repo target for a gated dashboard. | No | current repo |
| `target-ref` | Ref to dispatch on in `target-repo`. Empty ⇒ the PR head ref (same-repo). Set to the target's default branch (e.g. `master`) for cross-repo. | No | `''` |
| `dispatch-token` | Token used **only** for the cross-repo dispatch (needs `actions:write` on `target-repo`). Empty ⇒ `github.token` (same-repo only). | No | `''` |
| `target-workflow` | Filename of the host workflow to dispatch in `target-repo`. Lets one host repo serve several analyzers via per-analyzer host workflows (e.g. `performance-validation-html.yml`). | No | `performance-validation.yml` |

On cross-repo dispatch the action additionally passes `-f analyzer-repo=<caller repo>` so the host
can post the dashboard link back onto the analyzer PR.

## Requirements

- **Same-repo:** the caller job grants `actions:write`, `contents:read` and `pull-requests:read`.
- **Cross-repo:** the caller job grants `actions:read`, `contents:read`, `pull-requests:read`, `id-token:write`,
  and provides a `dispatch-token` with `actions:write` on `target-repo`.
- 
- The build workflow must upload a `candidate-version` artifact containing the deployed plugin version
  in `candidate-version.txt`.
