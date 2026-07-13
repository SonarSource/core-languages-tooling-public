# Ruling Update and Notify Action

Automatically updates ruling expected results when tests fail and posts diff comments to pull requests.

## Features

- **Automatic Ruling Sync**: Runs your sync command when ruling tests fail
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
      contents: write
      pull-requests: write
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

      - name: Update ruling and notify
        if: always()
        uses: SonarSource/core-languages-tooling-public/ruling-update-and-notify@master
        with:
          pr-number: ${{ github.event.pull_request.number }}
          ruling-failed: ${{ steps.ruling.outcome == 'failure' }}
          sync-command: 'mvn clean test -Pruling -Dupdate-expected'
          ruling-root: 'its/ruling/src/test/resources'
          sources-root: 'its/sources'
        env:
          GH_TOKEN: ${{ github.token }}
```

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `pr-number` | Pull request number (for PR events only) | No | `''` |
| `ruling-failed` | Whether the ruling test failed (true/false) | Yes | - |
| `sync-command` | Command to run to sync/update ruling expected results | Yes | - |
| `ruling-root` | Path to ruling expected results directory | Yes | - |
| `sources-root` | Path to ruling sources directory | No | `''` |
| `base-sha` | Base commit SHA for comparison | No | Auto-detected |
| `head-sha` | Head commit SHA for comparison | No | Current HEAD |
| `target-ref` | Target branch/ref name | No | Auto-detected |
| `base-ref` | Base branch/ref name | No | Auto-detected |
| `create-fix-pr` | Whether to create a fix PR when ruling fails | No | `'true'` |
| `fix-pr-branch-prefix` | Prefix for the fix PR branch name | No | `'fix/update-ruling-for'` |
| `repository` | Repository in format owner/repo | No | Current repository |

## Outputs

| Output | Description |
|--------|-------------|
| `has-differences` | Whether there are ruling differences (true/false) |
| `fix-pr-url` | URL of the fix PR if created |

## Behavior

1. **When ruling tests pass**: Posts a "no changes" comment to the PR
2. **When ruling tests fail with differences**:
   - Runs the sync command to update expected results
   - Posts a detailed diff comment to the PR
   - Creates or updates a fix PR with the updated results
   - Adds a comment linking to the fix PR
3. **When ruling tests fail but auto-update already happened**: Skips to prevent loops
4. **When ruling becomes up-to-date**: Closes any open fix PRs

## Requirements

- `gh` CLI must be available (usually pre-installed on GitHub runners)
- `uv` must be installed for the ruling-diff-comment action (use `astral-sh/setup-uv@v5`)
- Repository must have `contents: write` and `pull-requests: write` permissions

## How It Works

1. Detects if ruling test failed by checking the `ruling-failed` input
2. Checks last commit to prevent infinite auto-update loops
3. If ruling failed, runs the sync command to update expected results
4. Uses the `ruling-diff-comment` action to post detailed diff to PR
5. If there are differences and ruling failed:
   - Stashes the synced changes
   - Creates/updates a fix branch from the target branch
   - Commits the changes with a bot signature
   - Creates or updates a fix PR
   - Posts a comment on the original PR linking to the fix PR
6. If no differences or ruling passed:
   - Closes any stale fix PRs that may exist

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
