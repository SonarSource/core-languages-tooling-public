# Prepare Ruling Artifact Action

Packages generated ruling results as an `actual_*` artifact for
`ruling-update-and-notify`.

By default, the action finds `target/actual` (Maven) or `build/actual` (Gradle)
under `its/ruling` or `private/its/ruling`. It also accepts a repository-root
`build/actual` directory. It copies the contents under `expected/` in the
uploaded artifact, so a generated `project/xml-S123.json` becomes
`expected/project/xml-S123.json` when the notification action downloads it.
It fails if no directory exists, multiple candidates exist, or no JSON results
are found. Set `actual-root` to select a custom or ambiguous location.
Python 3 must be available as `python3` or `python` on the runner.

## Why a Separate Action?

Ruling tests may run in parallel jobs, each with its own workspace. Generated
results are local to those jobs, so this action uploads them for a downstream
`ruling-update-and-notify` job to consume. The test jobs can have read-only
repository permissions; only the update job needs permission to push a fix
branch and create a PR. This action does not modify expectations or create PRs.

Give each producer a unique `actual_*` artifact name. The update action merges
all matching artifacts into one expectation tree and creates one fix PR. If
multiple jobs generate the same project paths (for example, different OS
runs), select one canonical producer rather than merging conflicting results.

```yaml
- name: Prepare ruling artifact
  if: ${{ always() && steps.ruling.outcome == 'failure' }}
  uses: SonarSource/core-languages-tooling-public/prepare-ruling-artifact@master
```

| Input | Required | Default | Purpose |
|-------|----------|---------|---------|
| `actual-root` | No | Auto-detected | Override the generated results directory for another layout. |
| `artifact-name` | No | `actual_ruling` | Use a distinct `actual_*` name when multiple jobs upload results. |

Run after the ruling test in each producer job. Invoke
`ruling-update-and-notify` in a downstream job after the producers finish.
