# Ruling Update and Notify Action

Automatically updates ruling expected results when tests fail and posts diff comments to pull requests.

## Features

- **Automatic Ruling Sync**: Copies downloaded ruling artifacts when ruling tests fail
- **PR Comments**: Posts detailed ruling diff comments using the `ruling-diff-comment` action
- **Fix PR Creation**: Automatically creates a fix PR with updated ruling results, whose description includes the ruling diff summary
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

## Local Dry Run

After copying the actual ruling results into your analyzer checkout's expectation
directory, run the fix-PR script from that checkout:

```bash
python3 /path/to/core-languages-tooling-public/ruling-update-and-notify/create_fix_pr.py --dry-run
```

The script detects the ruling and sources roots using the supported repository
layouts. The target defaults to `master` on `origin`, or `main` if `master` does
not exist. Missing or ambiguous ruling layouts, or an origin with neither
branch, produce an error.

Optional command-line overrides are available:

| Option | Description |
|--------|-------------|
| `--target-ref BRANCH` | Target another branch instead of `master`/`main` |
| `--ruling-root PATH` | Use a specific ruling resources directory |
| `--sources-root PATH` | Use a specific sources directory |
| `--pr-number NUMBER` | Refer to the original PR in the preview |

Run with `--help` for all options. The action uses the same script and passes
its context through these command-line options; the script does not read
`TARGET_REF`, `RULING_ROOT`, `SOURCES_ROOT`, or `PR_NUMBER` from the environment.
Credentials and GitHub output plumbing still use `GH_TOKEN` and `GITHUB_OUTPUT`.

Dry-run fetches the target branch from `origin`, applies staged, unstaged, and
untracked ruling changes in a temporary worktree, and creates a temporary local
commit. It prints the proposed PR title, branches, and description, including
the ruling diff summary. It never pushes, calls `gh`, or writes `GITHUB_OUTPUT`.
No GitHub token or `GITHUB_OUTPUT` is needed; Git access to `origin` is still
required. The temporary worktree is removed, and your current branch, index,
and working files are left untouched. Fetching updates local remote-tracking refs.

This previews fix-PR creation only: it does not download or sync artifacts, post
the action's separate PR comments, or run stale-PR cleanup.

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

Artifacts prepared by `prepare-ruling-artifact` contain an `expected/` directory
and are copied into the detected ruling resources directory. For compatibility
with existing producers such as sonar-python-enterprise, artifacts without that
wrapper are copied into its `expected/` directory instead. All artifacts in a
run must use the same format.

## Inputs

| Input | Description | Required |
|-------|-------------|----------|
| `ruling-failed` | Whether the ruling test failed (`true` or `false`) | Yes |

When ruling tests fail, the action checks for exactly one of
the following layouts:

| Expectations directory | Sources directory |
|------------------------|-------------------|
| `its/ruling/src/test/resources/expected` | `its/sources` |
| `private/its/ruling/src/test/resources/expected` | `private/its/sources` |
| `private/its-enterprise/ruling/src/test/resources/expected` | `private/its-enterprise/sources_ruling` |

It reports an error if none or multiple expectation directories exist. Successful tests need no ruling
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
   - Creates or updates a fix PR with the updated results, including the ruling diff summary in its description
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
   - Creates a clean temporary worktree from the target branch and applies only ruling changes
   - Commits the changes with a bot signature and pushes the fix branch
   - Leaves the caller's checkout and unrelated changes untouched
   - Creates or updates a fix PR, embedding the output of the `ruling-diff-comment`
     script in its description (pull requests created with `GITHUB_TOKEN` do not
     trigger workflows, so the `ruling-diff-comment` action cannot run on them)
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
⚖️ Ruling update ready for review: https://github.com/org/repo/pull/123
```

## License

Copyright 2024-2025 SonarSource SA.
