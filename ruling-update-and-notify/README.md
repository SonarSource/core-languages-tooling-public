# Ruling Update and Notify Action

Automatically updates ruling expected results when tests fail and posts diff comments to pull requests.

## Features

- **Automatic Ruling Sync**: Copies downloaded ruling artifacts when ruling tests fail
- **PR Comments**: Posts detailed ruling diff comments using the `ruling-diff-comment` action
- **Publication Modes**: Creates a fix PR by default, or commits directly to the triggering PR branch when opted in
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
the expectation tree and publishes a fix PR (default) or a direct ruling commit.
This permits parallel ruling tests without giving test jobs permission to push
branches or create PRs. When tests
pass, the downstream job still runs to close an obsolete fix PR.

The consumer merges **all** `actual_*` artifacts and, in default mode, creates
**one** fix PR per target branch. Producers must write disjoint project paths, or one
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
| `update-mode` | `pull-request` (default) or `commit` | No |

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

### Commit Directly to the PR Branch

Set `update-mode: commit` to push the ruling update directly to the triggering
PR branch instead of creating a separate fix PR:

```yaml
- uses: actions/checkout@v4
  with:
    ref: ${{ github.event.pull_request.head.sha }}
    fetch-depth: 0

- name: Update ruling on the PR branch
  uses: SonarSource/core-languages-tooling-public/ruling-update-and-notify@master
  with:
    ruling-failed: ${{ needs.ruling.outputs.ruling-failed }}
    update-mode: commit
```

This mode is only supported for same-repository PR events; fork PRs and push
or other non-PR events are rejected. In workflows that also handle pushes,
select `pull-request` for those events or only invoke commit mode on PR events.
The publishing job still needs `contents: write` and `pull-requests: write`
permissions, with authenticated Git push access supplied by checkout.

Both the job producing the ruling artifacts and the downstream update job must
check out and use `github.event.pull_request.head.sha`, not the synthetic PR
merge commit. The update job checks that its checkout matches that SHA and
that the remote branch has not advanced. Stale runs fail rather than applying
old results to newer code. A normal, non-force push also rejects concurrent
branch updates while the ruling commit is being prepared.

Only changes under the detected ruling directory are included. The bot commit
is created in a temporary worktree, leaving the caller's checkout and unrelated
changes untouched. The existing auto-update marker prevents update loops.
The diff comment compares the old PR head with the pushed ruling commit.
No fix PR or fix-PR link comment is created, and stale fix-PR cleanup is disabled
in this mode. Any fix PR left from switching modes must be closed separately.

GitHub's built-in `GITHUB_TOKEN` does not trigger push workflows, and PR
synchronization workflows caused by it can require manual approval. If the
ruling commit must trigger unattended CI, configure checkout with an
appropriately scoped GitHub App token or PAT instead. See GitHub's
[workflow triggering documentation](https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-when-your-workflow-runs/triggering-a-workflow).
This action does not dispatch or rerun workflows itself.

## Outputs

| Output | Description |
|--------|-------------|
| `has-differences` | Whether there are ruling differences (true/false) |
| `fix-pr-url` | URL of the fix PR if created; empty in commit mode |
| `update-sha` | SHA pushed directly to the PR branch in commit mode; empty if no commit was pushed |

## Behavior

1. **When ruling tests pass**: Closes an open stale fix PR in `pull-request` mode; no publication in `commit` mode
2. **When ruling tests fail with differences**:
   - Downloads `actual_*` artifacts and copies them into the detected ruling directory
   - In `pull-request` mode, creates or updates a fix PR with the updated results
   - In `commit` mode, pushes a ruling-only commit to the unchanged PR head branch
   - Posts a detailed diff comment to the original PR
   - Adds a comment linking to the fix PR in `pull-request` mode only
3. **When ruling tests fail but auto-update already happened**: Skips to prevent loops
4. **When ruling becomes up-to-date**: Closes any open fix PRs in `pull-request` mode

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
   - Commits the changes with a bot signature and pushes the fix branch (default)
     or the triggering PR branch (`update-mode: commit`)
   - Leaves the caller's checkout and unrelated changes untouched
   - In default mode, creates or updates a fix PR and posts its link on the original PR
   - Uses the `ruling-diff-comment` action to compare the ruling commit with its actual base
5. If no differences or ruling passed:
   - Closes any stale fix PRs that may exist in default mode

Directory detection, artifact copying, fix-PR creation, and stale-PR cleanup
are implemented in `find_ruling_directory.py`, `sync_ruling_artifacts.py`,
`create_fix_pr.py`, `commit_ruling_update.py`, and `cleanup_fix_pr.py`. The composite action passes them
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
