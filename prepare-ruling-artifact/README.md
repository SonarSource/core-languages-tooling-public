# Prepare Ruling Artifact Action

Packages generated ruling results as an `actual_*` artifact for
`ruling-update-and-notify`.

By default, the action finds `target/actual` (Maven) or `build/actual` (Gradle)
under `its/ruling`, `private/its/ruling`, or `private/its-enterprise/ruling`.
It copies the contents under
`expected/` in the uploaded artifact, so a generated `project/xml-S123.json`
becomes `expected/project/xml-S123.json` when the notification action downloads it.
Both JSON (`.json`) and SARIF (`.sarif`) results are supported, including mixed
directories. Files retain their original names and contents; no format conversion
is performed.
It fails if none or multiple standard directories exist, or if the chosen
one contains no regular, non-symlink JSON or SARIF result files. Errors list the checked directories.
Python 3 must be available as `python3` or `python` on the runner.

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
`ruling-update-and-notify` in a downstream job after the producers finish.
