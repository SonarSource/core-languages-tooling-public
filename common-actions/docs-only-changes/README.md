# Docs-Only Changes

Composite action that inspects the files changed by a pull request or push and reports
whether the change is documentation-only (README, CONTRIBUTING, markdown docs, etc.), so a
caller workflow can skip its full build+test+scan pipeline for that change.

It calls the GitHub API directly (PR files / commit compare), so it does **not** require an
`actions/checkout` step to run.

## Why not just use `paths-ignore` on the trigger?

Putting `paths-ignore` on the workflow's `on:` trigger is tempting but breaks branch
protection: when every changed file matches `paths-ignore`, GitHub **never runs the
workflow at all**, so it never posts a status for any of that workflow's required checks.
A PR that only touches docs would then sit forever with its required checks stuck
"Expected — waiting for status to be reported".

Instead, keep the workflow triggered on everything, use this action to compute a
`docs-only` output, make the expensive jobs conditional on that output (they'll show as
**skipped**, not missing), and pair it with the
[`required-checks-gate`](../required-checks-gate) action so the branch-protection required
check always reports a result.

## Example Usage

```yaml
name: Build
on:
  pull_request:
  push:
    branches: [master]

jobs:
  detect-docs-only:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: read
    outputs:
      docs-only: ${{ steps.detect.outputs.docs-only }}
    steps:
      - id: detect
        uses: SonarSource/core-languages-tooling-public/common-actions/docs-only-changes@master
        with:
          github-token: ${{ github.token }}
          # Optional: override the defaults with repo-specific doc locations
          doc-patterns: '*.md,**/*.md,docs/**,LICENSE,NOTICE.*'

  build:
    needs: detect-docs-only
    if: needs.detect-docs-only.outputs.docs-only != 'true'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - run: ./build.sh

  # Configure THIS job (not `build`) as the required status check in branch protection.
  ci-required:
    needs: [detect-docs-only, build]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: SonarSource/core-languages-tooling-public/common-actions/required-checks-gate@master
        with:
          needs-context: ${{ toJSON(needs) }}
```

With this setup:
- A docs-only PR: `build` is skipped, `ci-required` still runs and reports success.
- A code-touching PR: `build` runs unchanged, `ci-required` reports its result.
- Either way, `ci-required` always reports a status, so branch protection never stalls.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `doc-patterns` | Comma-separated bash glob patterns (globstar/extglob enabled) matched against each changed file path. A change is docs-only when every changed file matches at least one pattern. | No | `*.md,**/*.md,docs/**,LICENSE,LICENSE.*,NOTICE,NOTICE.*,CONTRIBUTING,CONTRIBUTING.*,CODEOWNERS` |
| `github-token` | GitHub token used to list changed files via the GitHub API | Yes | |

## Outputs

| Output | Description |
|--------|-------------|
| `docs-only` | `'true'` when every changed file matches `doc-patterns`, `'false'` otherwise |
| `changed-files` | Newline-separated list of files used for the decision (useful for debugging) |

## Behavior notes

- Supported trigger events: `pull_request`, `pull_request_target`, and `push`. Any other
  event (`merge_group`, `workflow_dispatch`, `schedule`, ...) conservatively reports
  `docs-only=false` so the full pipeline always runs when the change set can't be
  determined from the event payload.
- A `push` to a brand-new branch (no previous commit to diff against) also reports
  `docs-only=false` for the same reason.
- Patterns are matched with bash's `globstar`/`extglob` enabled, so `**/*.md` matches
  markdown files at any depth and `docs/**` matches everything under `docs/`.
