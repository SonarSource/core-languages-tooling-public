# PVF Trigger

Composite action that, on a `/pvf` PR comment, resolves the candidate plugin version from the
latest **Build** run and dispatches the repo's `performance-validation.yml`.

It is a composite action (not a reusable workflow) on purpose: it runs as steps inside the caller's
job, so it adds no workflow-nesting level and does not consume the GitHub 4-level reusable-workflow
budget already used by the PVF framework chain.

Internally it calls the [`pvf-comment`](../pvf-comment) parser action. when a `/pvf` command is found invokes `performance-validation.yml`.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `comment` | Comment body to scan for a `/pvf` command | Yes | |
| `pr-number` | Pull request number the comment was posted on | Yes | |
| `build-workflow` | Filename of the build workflow that uploads the `candidate-version` artifact | No | `build.yml` |
| `rule-prefixes` | Space-separated rule-key prefixes passed to the parser | No | `S` |

## Requirements

- The caller job's grant `actions:write`, `contents:read` and `pull-requests:read` via the workflow `permissions:` block.
- The build workflow must upload a `candidate-version` artifact containing the deployed plugin version in `candidate-version.txt`.
