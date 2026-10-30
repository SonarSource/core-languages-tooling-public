# Ruling Diff Comment Action

This GitHub Action analyzes changes in ruling expectations and posts a human-readable summary as a PR comment.

## Purpose

When ruling test files are modified in a pull request, this action automatically:
1. Detects changed ruling expectation files
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

The action detects changed expectation files under any of:
```
its/ruling/src/test/resources/expected/<project-key>/
private/its/ruling/src/test/resources/expected/<project-key>/
private/its-enterprise/ruling/src/test/resources/expected/<project-key>/
```

Generated actual results live under `target/actual/<project-key>/` (Maven) or
`build/actual/<project-key>/` (Gradle). This action compares committed
expectations across revisions; it does not read generated actual files.

### Report Comparison

Each project has one expectation file per rule, named:
`<project-key>/<repo>-<rule>.sarif`.

Findings are read from
`runs[].results[].locations[].physicalLocation`. Within a rule report, findings
are compared by `artifactLocation.uri` (the source filename/component key) and
`region.startLine`, `startColumn`, `endLine`, `endColumn`, and the result's
`message.text`, as emitted by LITS.
Missing messages use an empty string. Messages are compared exactly, including
whitespace and case. Rule IDs and other metadata do not participate in comparison.
Findings are compared as
sets, so duplicate occurrences and result ordering do not affect comparison.

The parser follows the location information emitted by LITS:

- Precise findings retain the four range coordinates. Columns are already
  1-based UTF-16 positions (`columnKind: utf16CodeUnits`); no conversion is applied.
- Line-only findings contain `startLine` and `endLine`, without columns.
- File-level findings have no region and use line `0` internally.

An omitted `endLine` defaults to `startLine`, matching LITS. Missing columns use
integer `0` internally; all `IssueLocation` coordinates remain non-nullable.
Explicit coordinates must be positive integers. Character/byte offsets,
lengths, and rule IDs do not affect comparison.

Invalid locations produce an error identifying the report and revision. Changes
to any comparison field appear as removed and added findings. Comments include
range coordinates and issue messages, using base sources for removals and head
sources for additions. All findings are compared; a mismatch does not stop the diff.

### Source File Resolution

Source files for code snippets are resolved based on project name. The default looks for sources in:
```
private/its-enterprise/sources_ruling/{project}/
```

Override with the `sources-root` input parameter for different analyzers.

### Source Component Keys

`artifactLocation.uri` values emitted by LITS can include project/module
prefixes. These are stripped when resolving source files for snippets:

**Python format** (2-part):
```
airflow:airflow/cli/cli_parser.py
```
Extracts: `airflow/cli/cli_parser.py`

**Java Maven format** (3-part):
```
commons-beanutils:commons-beanutils:src/main/java/...
org.eclipse.jetty:jetty-project:jetty-http/src/main/...
```
Extracts: `src/main/java/...` or `jetty-http/src/main/...`

The action resolves both component-key conventions.

### Adapting for Different Analyzers

When using this action in a different analyzer repository:

1. **Set `sources-root` parameter** to match your sources directory
   - Java: `its/sources`
   - Python: `private/its-enterprise/sources_ruling`

2. **Ensure sources are available** at the specified path

3. **Configure workflow trigger paths** to include both supported expectation locations

See `example-workflow.yml` for a reference implementation.

## Development

### Running Tests

```bash
cd .github/actions/ruling-diff-comment
uv run python -m unittest discover -v -s . -p "test_*.py"
```

### Project Structure

- `action.yml` - Action metadata and workflow steps
- `ruling_diff.py` - Main entry point
- `ruling_diff_io.py` - Git and GitHub API interactions
- `ruling_diff_core.py` - Core module exports
- `ruling_diff_core_lib/` - Core logic modules
  - `models_and_constants.py` - Data models and configuration
  - `ruling_diff_logic.py` - Diff computation logic
  - `sarif.py` - SARIF report parsing
  - `snippet_generation.py` - Code snippet rendering
  - `comment_rendering.py` - Markdown comment formatting
- `test_ruling_diff.py` - Discovery, comparison, snippets, and GitHub interaction tests
- `test_sarif_diff.py` - SARIF parsing, range comparison, and Git integration tests

## License

See the LICENSE file in the repository root.
