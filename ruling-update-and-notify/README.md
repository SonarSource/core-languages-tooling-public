# Ruling Update and Notify Action

Automatically updates ruling expected results when tests fail and posts diff comments to pull requests.

## Features

- **Automatic Ruling Sync**: Copies downloaded ruling artifacts when ruling tests fail
- **PR Comments**: Posts detailed ruling diff comments using the `ruling-diff-comment` action
- **Fix PR Creation**: Automatically creates a fix PR with updated ruling results
- **Loop Prevention**: Detects and prevents infinite auto-update loops
- **Smart Cleanup**: Closes stale fix PRs when no longer needed

## Example Usage

The test jobs run the ruling tests and upload generated results; the update
job downloads them, updates the expectations, and creates the fix PR. Here two
parallel jobs test disjoint sets of projects.

```yaml
name: Build

on:
  pull_request:
  push:
    branches: [master]

jobs:
  ruling:
    strategy:
      fail-fast: false
      matrix:
        projects: [first-half, second-half]
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          submodules: true

      - name: Set up JDK
        uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'

      - name: Run ruling tests
        id: ruling
        # Writes its/ruling/target/actual/<project>/<rule>.json
        run: mvn verify -Pit-ruling -Dprojects=${{ matrix.projects }}

      - name: Prepare ruling artifact
        if: ${{ always() && steps.ruling.outcome == 'failure' }}
        # Uploads actual/<project>/<rule>.json as <project>/<rule>.json
        uses: SonarSource/core-languages-tooling-public/prepare-ruling-artifact@master
        with:
          artifact-name: actual_${{ matrix.projects }}

  ruling-update-notify:
    needs: ruling
    if: ${{ !cancelled() }}
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          submodules: true

      - name: Update ruling and notify
        # Copies <project>/<rule>.json to
        # its/ruling/src/test/resources/expected/<project>/<rule>.json
        uses: SonarSource/core-languages-tooling-public/ruling-update-and-notify@master
        with:
          ruling-failed: ${{ needs.ruling.result == 'failure' }}
```

Check out the test project sources (see [Inputs](#inputs) for their location,
usually a submodule) in the update job so that the PR comment can include code
snippets.

## Why Separate Jobs?

Test jobs generate local `target/actual` or `build/actual` results and upload
them as `actual_*` artifacts. A downstream job downloads those artifacts and
copies the result files into the selected expected directory before creating
a fix PR. This permits parallel ruling tests without giving test jobs
permission to push branches or create PRs. When tests pass, the downstream job
still runs to close an obsolete fix PR.

## Artifact Format

An `actual_*` artifact contains the generated results relative to the actual
directory, without any wrapper: `project/report.json` or
`project/report.sarif`. Each such file replaces
`<expected-root>/project/report.json` (or `.sarif`). Files are copied as is,
without format conversion.

The action downloads all `actual_*` artifacts outside the checkout and merges
them. Expectations for projects absent from the artifacts are kept, so jobs
that tested only part of the projects do not delete the others. The action
creates **one** fix PR per target branch. Producers must write disjoint
project paths, or one job must be chosen as the only producer of results for
overlapping projects; otherwise the last downloaded artifact wins. Per-project
fix PRs would require scoped artifact selection, unique fix-branch names, and
matching cleanup; the current actions do not provide that mode.

The sync step fails, instead of reporting that expectations are up to date,
when:

- the download fails or no `actual_*` artifact exists;
- the downloaded artifacts are empty or contain no regular JSON or SARIF file;
- the artifacts use the obsolete `expected/` wrapper of earlier
  `prepare-ruling-artifact` versions.

Only regular `.json` and `.sarif` files are copied: other files and symlinks in
the artifacts are ignored, and the action refuses to write through a symlink in
the expected directory.

## Inputs

| Input | Description | Required |
|-------|-------------|----------|
| `ruling-failed` | Whether the ruling test failed (`true` or `false`) | Yes |

When ruling tests fail, the action selects exactly one expected directory and
derives the sources directory from it:

| Layout | Expected directory | Sources for snippets |
|--------|--------------------|----------------------|
| Public | `its/ruling/src/test/resources/expected` | `its/sources` |
| Private | `private/its/ruling/src/test/resources/expected` | `private/its/sources` |
| Python enterprise | `private/its-enterprise/ruling/src/test/resources/expected` | `private/its-enterprise/sources_ruling` |

It reports the checked paths if none or several exist. Successful tests need no
ruling directory. Paths cannot be configured: callers should remove former
`pr-number`, `sources-root`, and `ruling-root` inputs.

PR details come from the GitHub event. On a push, the action can create or
clean up a fix PR, but it does not post a comment on an original PR.

## Outputs

| Output | Description |
|--------|-------------|
| `has-differences` | Whether there are ruling differences (true/false) |
| `fix-pr-url` | URL of the fix PR if created |

## Behavior

1. **When ruling tests pass**: Closes an open stale fix PR, if any
2. **When ruling tests fail with differences**:
   - Downloads `actual_*` artifacts and copies their result files into the selected expected directory
   - Creates or updates a fix PR with the updated results
   - Posts a detailed diff comment to the original PR
   - Adds a comment linking to the fix PR
3. **When ruling tests fail but auto-update already happened**: Skips to prevent loops
4. **When ruling becomes up-to-date**: Closes any open fix PRs

## Requirements

- `gh` CLI must be available (usually pre-installed on GitHub runners)
- Python 3 must be available on the runner
- The caller must check out the repository and upload `actual_*` artifacts when ruling tests fail; `prepare-ruling-artifact` uploads the standard ruling layout
- The job must have `contents: write` and `pull-requests: write` permissions
- `uv` is installed by this action when ruling fails

## How It Works

1. Detects if ruling test failed by checking the `ruling-failed` input
2. Checks last commit to prevent infinite auto-update loops
3. If ruling failed, downloads artifacts and copies their result files into the selected expected directory
4. Detects differences only in the selected expected directory
5. If there are differences and ruling failed:
   - Creates a clean temporary worktree from the target branch and applies and stages only changes in the expected directory
   - Commits the changes with a bot signature and pushes the fix branch
   - Leaves the caller's checkout and unrelated changes untouched
   - Creates or updates a fix PR
   - Posts a comment on the original PR linking to the fix PR
   - Uses the `ruling-diff-comment` action to compare the fix commit with its actual base, reading snippets from the matching sources directory
6. If no differences or ruling passed:
   - Closes any stale fix PRs that may exist

Directory detection, artifact copying, fix-PR creation, and stale-PR cleanup
are implemented in `find_ruling_directory.py`, `sync_ruling_artifacts.py`,
`create_fix_pr.py`, and `cleanup_fix_pr.py`. The composite action passes them
the GitHub context and publishes their outputs.

## Example PR Comment

When ruling differences are detected, the action posts a comment like:

```
## Ruling Changes

### python:S1234

**Added Issues (2)**
- `project/file.py:42` - New issue detected
- `project/other.py:15` - New issue detected

**Removed Issues (1)**
- `project/old.py:10` - Issue no longer detected

[View code snippet for project/file.py:42]
---
⚖️ Ruling update ready for review: https://github.com/org/repo/pull/123
```

## License

Copyright 2024-2025 SonarSource SA.
