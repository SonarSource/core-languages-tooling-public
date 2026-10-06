# PVF Resolve Baseline

Composite action that resolves a deployed baseline for a default-branch PVF run. Requires
Python 3 and `gh` on the runner, plus `actions: read` on the repository being queried. It does
not check out or execute code from candidate builds.

Selection order is the newest unexpired validated artifact from a push run of the selected
build workflow and branch, then a deployed build for `previous-sha`, then the newest deployed
branch build with a candidate artifact. Runs must have a successful publication job; their
overall status may still be in progress, failed or cancelled. The current run and candidate SHA
are excluded. GitHub results are paginated, and each download uses its own temporary directory.

| Input | Default / purpose |
| --- | --- |
| `repository`, `token` | Caller repository and GitHub token |
| `branch` | Caller repository's default branch |
| `build-workflow` | `build.yml` |
| `publication-job` | **Required** exact publication-job display name |
| `previous-sha` | Empty; pre-push SHA for the first fallback |
| `current-sha`, `current-run-id` | Caller SHA and run ID; excluded from selection |
| `validated-artifact` | `pvf-validated` |
| `candidate-artifact` | `candidate-version` |

Each artifact must contain `<artifact-name>.txt` with one nonempty version token. Outputs
`baseline-version` and `baseline-sha` are empty when no baseline exists. Missing/expired artifacts
are skipped; malformed version files warn and are skipped. API/authentication and download errors
fail the action instead of silently choosing another baseline.

```yaml
- id: baseline
  uses: SonarSource/core-languages-tooling-public/pvf-resolve-baseline@master
  with:
    publication-job: Publish CLI Artifacts
    previous-sha: ${{ github.event.before }}
```

The caller decides whether to skip validation when the output is empty, and records
`pvf-validated.txt` after completed validation. A reported regression can still advance that
baseline; a failed or cancelled validation must not.

Run tests: `python3 -m unittest discover -v -s pvf-resolve-baseline -p 'test_*.py'`.
