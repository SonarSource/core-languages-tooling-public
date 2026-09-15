# Required Checks Gate

Composite action that turns a set of possibly-skipped jobs into a single, always-reporting
job — the one you configure as a branch-protection required check.

## Why this is needed

A job that's individually made conditional (e.g.
`if: needs.detect-docs-only.outputs.docs-only != 'true'`) still reports a `skipped` status,
which branch protection accepts as passing — so in principle you *could* require that job
directly. In practice that's fragile: the job's name can change (matrix builds), a repo
often has several independently-conditional jobs and you don't want to list every one of
them in branch protection, and it's easy to accidentally reintroduce the "stuck pending"
problem the moment someone adds a trigger-level `paths-ignore` (see
[docs-only-changes](../docs-only-changes) for why that breaks things).

This gate job fixes the required-check name once and for all: it always runs
(`if: always()`, no path-dependent `if:` of its own) and turns the results of whichever
upstream jobs actually ran into a single pass/fail outcome, so it's a stable, safe target
for branch protection regardless of which of its dependencies were skipped.

## Example Usage

```yaml
jobs:
  detect-docs-only:
    # ... produces outputs.docs-only ...

  build:
    needs: detect-docs-only
    if: needs.detect-docs-only.outputs.docs-only != 'true'
    # ... expensive pipeline ...

  ci-required:
    needs: [detect-docs-only, build]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: SonarSource/core-languages-tooling-public/common-actions/required-checks-gate@master
        with:
          needs-context: ${{ toJSON(needs) }}
```

Set `ci-required` (not `build`) as the required status check in branch protection.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `needs-context` | JSON-encoded `needs` context from the calling workflow (`${{ toJSON(needs) }}`) | Yes | |

## Behavior

- Fails if any job referenced in `needs-context` has result `failure` or `cancelled`.
- Passes if every job has result `success` or `skipped`.
