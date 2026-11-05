# Ruling Update and Notify Action

Consumes ruling artifacts after test failures, commits the updated expectations
directly to the triggering PR branch, and posts a ruling diff comment. This
action only supports same-repository PR events.

## Example Usage

Keep test jobs read-only and publish their ruling artifacts from a separate
job with write permissions. Both jobs must check out the triggering PR's head
SHA, not GitHub's synthetic PR merge commit.

```yaml
name: Build

on:
  pull_request:

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
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0

      - name: Set up JDK
        uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'

      - name: Run ruling tests
        id: ruling
        continue-on-error: true
        run: mvn clean test -Pruling

      - name: Prepare ruling artifact
        if: ${{ always() && steps.ruling.outcome == 'failure' }}
        uses: SonarSource/core-languages-tooling-public/prepare-ruling-artifact@master

  ruling-update-notify:
    needs: ruling
    if: >-
      always() && needs.ruling.result == 'success' &&
      github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0

      - name: Update ruling and notify
        uses: SonarSource/core-languages-tooling-public/ruling-update-and-notify@master
        with:
          ruling-failed: ${{ needs.ruling.outputs.ruling-failed }}
```

## Inputs

| Input | Description | Required |
|-------|-------------|----------|
| `ruling-failed` | Whether the ruling test failed (`true` or `false`) | Yes |

The PR number, head branch, and tested head SHA come from the event. Fork PRs,
push events, and other events without PR context are rejected. Only invoke this
action for same-repository PRs, as in the example above.

When ruling tests fail, the action detects exactly one of these layouts:

| Expectations directory | Sources directory |
|------------------------|-------------------|
| `its/ruling/src/test/resources/expected` | `its/sources` |
| `private/its/ruling/src/test/resources/expected` | `private/its/sources` |
| `private/its-enterprise/ruling/src/test/resources/expected` | `private/its-enterprise/sources_ruling` |

Missing or ambiguous expectation directories are errors. Passing tests do not
require a ruling directory or artifacts.

## Artifacts

Test jobs upload `actual_*` artifacts using `prepare-ruling-artifact`. The
update job merges all of them into one ruling update. Producers must write
disjoint project paths, or choose one platform as the source for overlapping
projects.

Artifacts prepared by `prepare-ruling-artifact` contain an `expected/`
directory and are copied into the detected ruling resources directory. Legacy
artifacts without that wrapper are copied into its `expected/` directory
instead. All artifacts in a run must use the same format.

## Behavior

1. Validates the failure flag and same-repository PR context.
2. If tests passed, does nothing further.
3. If the last commit carries the auto-update marker, skips the update to
   prevent loops.
4. Downloads ruling artifacts and syncs them into the detected expectations.
5. Verifies that the checkout and remote branch still match the triggering
   PR head SHA. Stale runs fail instead of applying old results to newer code.
6. Uses a temporary worktree to commit only ruling changes with the bot
   identity. The caller's checkout and unrelated changes remain untouched.
7. Pushes the commit directly to the PR branch with an explicit expected-SHA
   lease. The new commit extends the verified PR head; the push fails if the
   remote tip no longer matches, including after an advance, rewind, or branch
   deletion. No differences means no commit or push.
8. Posts or updates the ruling diff comment on the original PR, comparing
   the previous head with the newly pushed ruling commit.

The action never creates update branches or additional PRs, and does not
manage or close existing PRs.

## Outputs

| Output | Description |
|--------|-------------|
| `has-differences` | `true` when a ruling update was committed and pushed; otherwise `false` |
| `update-sha` | SHA pushed to the PR branch, or empty when no commit was pushed |

## Requirements

- Python 3 and the `gh` CLI must be available on the runner.
- The caller must check out `github.event.pull_request.head.sha` in both
  the test and update jobs and upload `actual_*` artifacts on ruling failures.
- The update job needs `contents: write` and `pull-requests: write`
  permissions, with authenticated Git push access supplied by checkout.
- `uv` is installed by the action when a ruling update is needed.

GitHub's built-in `GITHUB_TOKEN` does not trigger push workflows, and PR
synchronization workflows caused by it can require manual approval. If the
ruling commit must trigger unattended CI, configure checkout with an
appropriately scoped GitHub App token or PAT instead. See GitHub's
[workflow triggering documentation](https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-when-your-workflow-runs/triggering-a-workflow).
This action does not dispatch or rerun workflows itself.

## Implementation

- `find_ruling_directory.py` detects the expectation and source paths.
- `sync_ruling_artifacts.py` copies downloaded artifacts.
- `commit_ruling_update.py` handles the Git operations and publishes the
  before/after commit SHAs used by the ruling diff comment.

## License

Copyright 2024-2025 SonarSource SA.
