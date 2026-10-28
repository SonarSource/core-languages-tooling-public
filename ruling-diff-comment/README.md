# Ruling Diff Comment Action

This GitHub Action analyzes changes in ruling JSON files and posts a human-readable summary as a PR comment.

## Purpose

When ruling test files are modified in a pull request, this action automatically:
1. Detects changed ruling JSON files
2. Compares before/after versions to identify issue differences
3. Generates code snippets showing where new issues appear or old issues were fixed
4. Posts or updates a comment on the PR with a formatted summary

This helps reviewers understand the impact of code changes on static analysis results.

## Usage

Add this action to your workflow:

```yaml
- name: Post ruling diff comment
  uses: ./.github/actions/ruling-diff-comment
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  with:
    pr-number: ${{ github.event.pull_request.number }}
    repository: ${{ github.repository }}
    base-sha: ${{ github.event.pull_request.base.sha }}
    head-sha: ${{ github.event.pull_request.head.sha }}
    # Optional: customize for different analyzers
    # sources-root: 'its/sources'                    # For Java
```

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `pr-number` | Pull request number | Yes | - |
| `repository` | Repository in `owner/repo` format | Yes | - |
| `base-sha` | Base commit SHA for comparison | Yes | - |
| `head-sha` | Head commit SHA for comparison | Yes | - |
| `sources-root` | Path to sources directory | No | `private/its-enterprise/sources_ruling` |

## Requirements

- `uv` must be installed in the workflow environment
- `gh` CLI must be configured with appropriate permissions
- Repository must contain ruling files in the expected structure

## Environment Variables

- `GH_TOKEN`: GitHub token for posting comments (required)
- `RUNNER_DEBUG`: Set to `1` to enable debug logging (optional)

## Configuration

### Ruling File Location

The action detects changed expectation JSON files under any of:
```
its/ruling/src/test/resources/expected/<project-key>/
private/its/ruling/src/test/resources/expected/<project-key>/
private/its-enterprise/ruling/src/test/resources/expected/<project-key>/
```

Generated actual results live under `target/actual/<project-key>/` (Maven) or
`build/actual/<project-key>/` (Gradle). This action compares committed
expectations across revisions; it does not read generated actual files.

### Source File Resolution

Source files for code snippets are resolved based on project name. The default looks for sources in:
```
private/its-enterprise/sources_ruling/{project}/
```

Override with the `sources-root` input parameter for different analyzers.

### Ruling JSON Key Formats

The action supports different ruling JSON key formats:

**Python format** (2-part):
```
"airflow:airflow/cli/cli_parser.py": [42]
```
Extracts: `airflow/cli/cli_parser.py`

**Java Maven format** (3-part):
```
"commons-beanutils:commons-beanutils:src/main/java/...": [42]
"org.eclipse.jetty:jetty-project:jetty-http/src/main/...": [42]
```
Extracts: `src/main/java/...` or `jetty-http/src/main/...`

The action automatically detects and handles both formats.

### Adapting for Different Analyzers

When using this action in a different analyzer repository:

1. **Set `sources-root` parameter** to match your sources directory
   - Java: `its/sources`
   - Python: `private/its-enterprise/sources_ruling`

2. **Ensure sources are available** at the specified path

3. **Configure workflow trigger paths** to include both supported expectation locations

See `example-workflow.yml` for a reference implementation.

## Development

### Previewing Real Ruling Changes Locally

Use the same entry point as the action with `--dry-run` to generate the comment
without posting to GitHub. PR number, repository, and GitHub credentials are not
required in this mode. Python 3.10+ is sufficient; there are no package dependencies.

```bash
cd /path/to/analyzer-checkout
python3 /path/to/core-languages-tooling-public/ruling-diff-comment/ruling_diff.py \
  --dry-run \
  --base-sha HEAD~1 \
  --head-sha HEAD \
  --sources-root its/sources \
  > /tmp/ruling-comment.md
```

Open `/tmp/ruling-comment.md` in a Markdown previewer to inspect the result.
Markdown goes to stdout; diagnostic logging goes to stderr. If there are no
changed ruling JSON files or no issue deltas, stdout is empty.

Run from the analyzer repository root. Both revisions must exist locally, and
the comparison uses Git's three-dot diff (`base...head`), just like the action.
Uncommitted expectations and generated `target/actual` or `build/actual` files
are not compared: for freshly generated results, sync them into expectations
in a disposable checkout and make a local-only commit first. No push is needed.

Set `--sources-root` to the analyzer's source location (for example,
`its/sources` or `private/its/sources`). Sources and any required submodule
commits should be available locally for snippets; missing submodule content can
trigger a Git fetch. Optional `--ruling-root` overrides the standard expected
directories. The comment renderer currently compares JSON files, not SARIF.

Without `--dry-run`, the existing posting behavior is unchanged and
`--pr-number` and `--repository` are required.

### Running Tests

```bash
cd ruling-diff-comment
python3 -m unittest discover -v -s . -p "test_ruling_diff.py"
```

The tests cover CLI validation and preview/posting behavior, plus an integration
test that renders real ruling changes from a temporary local Git repository.
GitHub interactions are tested with mocks rather than creating real PRs.

### Project Structure

- `action.yml` - Action metadata and workflow steps
- `ruling_diff.py` - Main entry point
- `ruling_diff_io.py` - Git and GitHub API interactions
- `ruling_diff_core.py` - Core module exports
- `ruling_diff_core_lib/` - Core logic modules
  - `models_and_constants.py` - Data models and configuration
  - `ruling_diff_logic.py` - Diff computation logic
  - `snippet_generation.py` - Code snippet rendering
  - `comment_rendering.py` - Markdown comment formatting
- `test_ruling_diff.py` - Unit tests

## License

See the LICENSE file in the repository root.
