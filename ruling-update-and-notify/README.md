# Ruling Update and Notify Action

Automatically updates ruling expected results when tests fail and posts diff comments to pull requests.

## Features

- **Automatic Ruling Sync**: Copies downloaded ruling artifacts when ruling tests fail
- **PR Comments**: Posts detailed ruling diff comments using the `ruling-diff-comment` action
- **Fix PR Creation**: Automatically creates a fix PR with updated ruling results
- **Loop Prevention**: Detects and prevents infinite auto-update loops
- **Smart Cleanup**: Closes stale fix PRs when no longer needed

## Example Usage

```yaml
name: Build

on:
  pull_request:
  push:
    branches: [master]

jobs:
  ruling:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    outputs:
      ruling-failed: ${{ steps.ruling.outcome == 'failure' }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up JDK
        uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'

      - name: Run ruling tests
        id: ruling
        continue-on-error: true
        run: |
          mvn clean test -Pruling

      - name: Prepare ruling artifact
        if: ${{ always() && steps.ruling.outcome == 'failure' }}
        uses: SonarSource/core-languages-tooling-public/prepare-ruling-artifact@master

  ruling-update-notify:
    needs: ruling
    if: ${{ always() && needs.ruling.result == 'success' }}
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Update ruling and notify
        uses: SonarSource/core-languages-tooling-public/ruling-update-and-notify@master
        with:
          ruling-failed: ${{ needs.ruling.outputs.ruling-failed }}
```

## Why Separate Jobs?

Test jobs generate local `target/actual` or `build/actual` results and upload
them as `actual_*` artifacts. A downstream job downloads those artifacts into
the expectation tree and creates a fix PR. This permits parallel ruling tests
without giving test jobs permission to push branches or create PRs. When tests
pass, the downstream job still runs to close an obsolete fix PR.

The current consumer merges **all** `actual_*` artifacts and creates **one**
fix PR per target branch. Producers must write disjoint project paths, or one
platform must be selected as the canonical source for overlapping projects.
Per-project fix PRs would require scoped artifact selection, unique fix-branch
names, and matching cleanup; the current actions do not provide that mode.

## Inputs

| Input | Description | Required |
|-------|-------------|----------|
| `ruling-failed` | Whether the ruling test failed (`true` or `false`) | Yes |

When ruling tests fail, the action checks for exactly one of
`its/ruling/src/test/resources/expected` and
`private/its/ruling/src/test/resources/expected`. It reports both paths if
neither or both exist, and uses the corresponding `its/sources` or
`private/its/sources` path for snippets. Successful tests need no ruling
directory. PR context comes from the event; callers should remove former
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
   - Downloads `actual_*` artifacts and copies them into the detected ruling directory
   - Creates or updates a fix PR with the updated results
   - Posts a detailed diff comment to the original PR
   - Adds a comment linking to the fix PR
3. **When ruling tests fail but auto-update already happened**: Skips to prevent loops
4. **When ruling becomes up-to-date**: Closes any open fix PRs

## Requirements

- `gh` CLI must be available (usually pre-installed on GitHub runners)
- Python 3 must be available on the runner
- The caller must check out the repository and upload `actual_*` artifacts when ruling tests fail; `prepare-ruling-artifact` packages the standard ruling layout
- The job must have `contents: write` and `pull-requests: write` permissions
- `uv` is installed by this action when ruling fails

## How It Works

1. Detects if ruling test failed by checking the `ruling-failed` input
2. Checks last commit to prevent infinite auto-update loops
3. If ruling failed, downloads artifacts and copies them into the detected ruling directory
4. If there are differences and ruling failed:
   - Stashes the synced changes
   - Creates/updates a fix branch from the target branch
   - Commits the changes with a bot signature
   - Creates or updates a fix PR
   - Posts a comment on the original PR linking to the fix PR
   - Uses the `ruling-diff-comment` action to compare the fix commit with its actual base
5. If no differences or ruling passed:
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
❌ **Ruling needs updating.** A fix PR has been created: https://github.com/org/repo/pull/123

Please review and merge it into your branch.
```

## License

Copyright 2024-2025 SonarSource SA.
