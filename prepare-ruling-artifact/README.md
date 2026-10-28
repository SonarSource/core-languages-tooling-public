# Prepare Ruling Artifact Action

Uploads generated ruling results as an `actual_*` artifact for
`ruling-update-and-notify`.

The action selects exactly one generated-result directory:

| Layout | Maven | Gradle |
|--------|-------|--------|
| Public | `its/ruling/target/actual` | `its/ruling/build/actual` |
| Private | `private/its/ruling/target/actual` | `private/its/ruling/build/actual` |
| Python enterprise | `private/its-enterprise/ruling/target/actual` | `private/its-enterprise/ruling/build/actual` |

It fails if none or several of these directories exist, and the error lists
the checked directories. It also fails if the selected directory contains no
regular (non-symlink) `.json` or `.sarif` file. JSON and SARIF results may be
mixed in the same directory.

The selected directory is uploaded directly, without copying or converting
files: a generated `actual/project/report.json` is stored as
`project/report.json` in the artifact, and `ruling-update-and-notify` copies it
to `expected/project/report.json`. Python 3 must be available as `python3` or
`python` on the runner.

> **Artifact format change:** earlier versions wrapped the results in an
> `expected/` directory. `ruling-update-and-notify` rejects artifacts using that
> wrapper, so update both actions together, as well as any workflow step that
> uploads `actual_*` artifacts manually.

## Why a Separate Action?

Ruling tests can run in separate jobs, which do not share generated files.
This action uploads those files for `ruling-update-and-notify` to consume later.

```yaml
- name: Ruling tests
  id: ruling
  continue-on-error: true
  run: ./gradlew :its:ruling:test
- name: Prepare ruling artifact
  id: prepare-ruling-artifact
  if: ${{ steps.ruling.outcome == 'failure' }}
  uses: SonarSource/core-languages-tooling-public/prepare-ruling-artifact@master
  with:
    artifact-name: actual_${{ matrix.projects }}
- name: Fail on ruling test failure
  if: ${{ !cancelled() && steps.ruling.outcome == 'failure' && steps.prepare-ruling-artifact.outcome == 'success' }}
```

| Input | Required | Default | Purpose |
|-------|----------|---------|---------|
| `artifact-name` | No | `actual_ruling` | Use a distinct `actual_*` name when multiple jobs upload results. |

| Output | Purpose |
|--------|---------|
| `artifact-id` | ID of the uploaded artifact. |
| `artifact-url` | Link to the uploaded artifact, also printed as a notice and in the job summary. |

Use `artifact-url` to point to the exact uploaded artifact in diagnostic messages:

```yaml
- name: Prepare ruling artifact
  id: prepare-ruling-artifact
  if: ${{ steps.ruling.outcome == 'failure' }}
  uses: SonarSource/core-languages-tooling-public/prepare-ruling-artifact@master
- name: Fail on ruling test failure
  if: ${{ !cancelled() && steps.ruling.outcome == 'failure' && steps.prepare-ruling-artifact.outcome == 'success' }}
  env:
    ARTIFACT_URL: ${{ steps.prepare-ruling-artifact.outputs.artifact-url }}
  run: |
    echo "Ruling tests failed. Actual results: ${ARTIFACT_URL}"
    exit 1
```

The `steps.prepare-ruling-artifact.outcome == 'success'` guard avoids printing a
misleading message when the artifact could not be uploaded; the job still fails
because of the failing `Prepare ruling artifact` step.

Run after the ruling test in each producer job. Invoke
`ruling-update-and-notify` in a downstream job after the producers finish; see
its README for a complete workflow. Jobs running in parallel must produce
results for disjoint projects, because the update job merges all artifacts.
