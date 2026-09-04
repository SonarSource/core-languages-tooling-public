# PVF Trigger

Composite action that, on a `/pvf` PR comment, resolves the candidate plugin version from the
latest **Build** run and dispatches `performance-validation.yml`.

It is a composite action (not a reusable workflow) on purpose: it runs as steps inside the caller's
job, so it adds no workflow-nesting level and does not consume the GitHub 4-level reusable-workflow
budget already used by the PVF framework chain.

Internally it calls the [`pvf-comment`](../pvf-comment) parser action. When a `/pvf` command is found
it invokes `performance-validation.yml` — either in the caller repo (default) or in a separate
dashboard-host repo.

## Two modes

- **Same-repo (default):** `performance-validation.yml` lives in the caller repo and publishes to the
  caller's own GitHub Pages. This is the original behaviour and requires no new inputs. It fits
  **private/internal** analyzer repos (e.g. `sonar-python-enterprise`) whose Pages are already
  access-controlled.
- **Cross-repo:** a **public** analyzer repo dispatches into a separate **private/internal**
  dashboard-host repo, which runs the benchmark and publishes to *its* access-controlled (SSO-gated)
  Pages — so no unauthenticated Pages site is ever created. Set `target-repo`, `target-ref` and
  `dispatch-token`.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `comment` | Comment body to scan for a `/pvf` command | Yes | |
| `pr-number` | Pull request number the comment was posted on | Yes | |
| `build-workflow` | Filename of the build workflow that uploads the `candidate-version` artifact | No | `build.yml` |
| `rule-prefixes` | Space-separated rule-key prefixes passed to the parser | No | `S` |
| `target-repo` | `owner/name` of the repo hosting `performance-validation.yml`. Cross-repo target for a gated dashboard. | No | current repo |
| `target-ref` | Ref to dispatch on in `target-repo`. Empty ⇒ the PR head ref (same-repo). Set to the target's default branch (e.g. `master`) for cross-repo. | No | `''` |
| `dispatch-token` | Token used **only** for the cross-repo dispatch (needs `actions:write` on `target-repo`). Empty ⇒ `github.token` (same-repo only). | No | `''` |

On cross-repo dispatch the action additionally passes `-f analyzer-repo=<caller repo>` so the host
can post the dashboard link back onto the analyzer PR. Same-repo dispatch omits it, so a host
`performance-validation.yml` without an `analyzer-repo` input keeps working.

## Requirements

- **Same-repo:** the caller job grants `actions:write`, `contents:read` and `pull-requests:read`.
- **Cross-repo:** the caller job grants `actions:read` (download the `candidate-version` artifact),
  `contents:read`, `pull-requests:read`, and provides a `dispatch-token` (Vault- or GitHub-App-issued)
  with `actions:write` on `target-repo`. `id-token:write` is needed if fetching the token via Vault.
- The build workflow must upload a `candidate-version` artifact containing the deployed plugin version
  in `candidate-version.txt`.
