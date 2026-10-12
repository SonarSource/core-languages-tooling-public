# PVF Resolve Latest Validated Master

Find a deployed baseline on the repository's default branch. Requires Python 3, `gh`, and a
GitHub token with `actions: read`. Uses the repository's default branch (`main`, `master`, or
another name) unless `branch` overrides it.

## Selection

Walk push builds of `build-workflow` from newest to oldest. Exclude **every build of
`current-sha`**, even if its version or run ID differs. A different commit can be a baseline
regardless of its build version. Each eligible build must have a successful `publication-job`;
the overall workflow does not have to be successful or finished.

1. Prefer a usable, unexpired `pvf-validated` artifact on a recent build.
2. Stop at the latest eligible published build from the **previous UTC calendar day**. Prefer
   its validated artifact; otherwise use its `candidate-version` artifact, even though that
   version has not completed PVF.
3. If that day has no eligible build, use the nearest earlier eligible published build. Do not
   search past an eligible fallback for an older validated baseline.

The date boundary is midnight UTC on the day the action runs, using workflow-run creation times.
It is not a rolling 24-hour window. For example, on Wednesday October 7, a Tuesday build at
23:59 UTC can be the fallback; an unvalidated Wednesday build cannot. After a weekend, the
fallback can be Friday's latest eligible build. This bounds the search for validated markers;
finding an eligible published fallback can still require paging through older builds.

The validated (`pvf-validated`) and candidate (`candidate-version`) artifacts each contain
`<artifact-name>.txt` with one nonempty version token. Missing, expired, or malformed artifacts
are skipped. If no usable baseline exists, `baseline-version` and
`baseline-sha` are empty, allowing the caller to skip validation. API/authentication or download
failures fail the action rather than silently selecting another baseline. Downloads use separate
temporary directories and never execute candidate code.

## Inputs and outputs

| Input | Default / purpose |
| --- | --- |
| `repository`, `token` | Caller repository and GitHub token |
| `branch` | Caller repository's default branch |
| `build-workflow` | `build.yml` |
| `publication-job` | **Required** exact publication-job display name |
| `current-sha` | Caller SHA; all builds of this commit are excluded |

Outputs are `baseline-version` and `baseline-sha`.

```yaml
- id: baseline
  uses: SonarSource/core-languages-tooling-public/pvf-resolve-latest-validated-master@master
  with:
    publication-job: Publish CLI Artifacts
```

The caller writes `pvf-validated.txt` after **completed validation**, including runs reporting
regressions. Failed or cancelled validation must not advance the marker. This measures changes
since the last completed validation, rather than since the last regression-free build.

Run tests: `python3 -m unittest discover -v -s pvf-resolve-latest-validated-master -p 'test_*.py'`.
