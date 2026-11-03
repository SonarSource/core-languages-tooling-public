# PVF Resolve Baseline

Composite action that resolves the PVF baseline of a push to the default branch, so the push can
be benchmarked against the plugin built for the commit before it.

It runs as steps inside the caller's job. The baseline is the plugin version that
[`prepare-pvf`](../prepare-pvf) recorded as the `candidate-version` artifact in the previous commit's
**Build** run. The result goes to the host workflow's `baseline-version`, and
[`pvf-notify-merger`](../pvf-notify-merger) uses `baseline-sha` to link the compared range.

## How the baseline is resolved

1. **Opt-out:** when the PR merged by the push has the `skip-pvf` label or `[skip pvf]` in its title,
   the push is skipped (`skip-reason: opt-out`). For example, rule-metadata update PRs are labelled
   `skip-pvf` by their automations.
2. **Paths:** when `skip-paths` is set and every file changed by the push matches it, the push is
   skipped (`skip-reason: skip-paths`). Pushes changing 300 files or more are never skipped, as the
   compare API may not list them all.
3. **Previous commit:** the `candidate-version` artifact of the previous commit's Build run.
   - While that run can still record it, the action polls every minute, for up to `wait-minutes`
     shared by all runs of that commit.
   - With `publication-job` set, it stops as soon as that job finishes, whatever its conclusion. A
     skipped or failed job means the run won't record a version, even though the run keeps going.
   - Without `publication-job`, it waits for the whole run.
4. **Fallback:** the newest earlier Build run on `branch` that recorded a version. The comparison
   then spans several merges, which `baseline-sha` makes visible.
5. **Nothing found:** no baseline, with a warning (`skip-reason: no-baseline`), e.g. right after
   adopting `prepare-pvf`.

API calls are retried, and while waiting a failed call is retried on the next poll, so a single 5xx
or rate-limit response does not abort the step. A failure of the essential run listings after the
retries fails the step.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `previous-sha` | Commit before the push (`github.event.before`). Empty or all zeros (branch creation) goes straight to the fallback. | Yes | |
| `current-sha` | Commit of the push. Its merged PR is checked for the opt-out; its own Build run is never the baseline. | No | `github.sha` |
| `build-workflow` | Filename of the Build workflow that records `candidate-version` | No | `build.yml` |
| `publication-job` | Name of the Build job that records `candidate-version` (e.g. `Prepare PVF`). Empty waits for the whole run. | No | `''` |
| `wait-minutes` | Total time to wait for in-progress runs of the previous commit | No | `45` |
| `skip-paths` | Extended regex; a push changing only matching files is skipped (e.g. rule metadata and docs). Empty never skips on paths. | No | `''` |
| `branch` | Branch whose Build runs are considered | No | default branch |
| `token` | Token with `actions:read`, `contents:read` and `pull-requests:read` | No | `github.token` |

## Outputs

| Output | Description |
|--------|-------------|
| `baseline-version` | Plugin version to use as the baseline. Empty when the push is skipped or nothing was found. |
| `baseline-sha` | Commit the baseline was built from. Differs from `previous-sha` when the fallback was used. |
| `skip-reason` | `opt-out`, `skip-paths` or `no-baseline` when no baseline is returned, empty otherwise. |

## Usage

```yaml
resolve_baseline:
  runs-on: sonar-xs
  # Allows the wait-minutes wait.
  timeout-minutes: 60
  permissions:
    actions: read
    contents: read
    pull-requests: read
  outputs:
    baseline-version: ${{ steps.resolve.outputs.baseline-version }}
    baseline-sha: ${{ steps.resolve.outputs.baseline-sha }}
  steps:
    - id: resolve
      uses: SonarSource/core-languages-tooling-public/pvf-resolve-baseline@master
      with:
        previous-sha: ${{ github.event.before }}
        publication-job: Prepare PVF
        skip-paths: '/src/main/resources/(org|com)/sonar/l10n/[^/]+/rules/|sonarpedia\.json$|\.md$|^docs/'
```

## Requirements

- `gh` CLI and `jq` on the runner.
- The Build workflow uploads the `candidate-version` artifact with [`prepare-pvf`](../prepare-pvf),
  after the plugin is deployed.
- The calling job's `timeout-minutes` leaves room for `wait-minutes`.
