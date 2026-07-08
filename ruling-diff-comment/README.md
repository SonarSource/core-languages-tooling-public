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
```

## Inputs

| Input | Description | Required |
|-------|-------------|----------|
| `pr-number` | Pull request number | Yes |
| `repository` | Repository in `owner/repo` format | Yes |
| `base-sha` | Base commit SHA for comparison | Yes |
| `head-sha` | Head commit SHA for comparison | Yes |

## Requirements

- `uv` must be installed in the workflow environment
- `gh` CLI must be configured with appropriate permissions
- Repository must contain ruling files in the expected structure

## Environment Variables

- `GH_TOKEN`: GitHub token for posting comments (required)
- `RUNNER_DEBUG`: Set to `1` to enable debug logging (optional)

## Configuration

### Ruling File Location

The action expects ruling files to be located under:
```
private/its-enterprise/ruling/src/test/resources/expected_ruling/
```

This path is configured in `ruling_diff_core_lib/models_and_constants.py` via the `EXPECTED_RULING_ROOT` constant.

### Source File Resolution

Source files for generating code snippets are resolved based on project name. The default behavior looks for sources in:
```
private/its-enterprise/sources_ruling/{project}/
```

For analyzers with different source layouts, you can configure project-specific overrides in `ruling_diff_core_lib/models_and_constants.py` by modifying the `PROJECT_SOURCE_OVERRIDES` dictionary.

### Adapting for Different Analyzers

When using this action in a different analyzer repository:

1. Verify the `EXPECTED_RULING_ROOT` matches your ruling directory structure
2. Update `PROJECT_SOURCE_OVERRIDES` if your ruling sources use different paths
3. Ensure your workflow initializes any necessary submodules before running the action
4. Configure the workflow trigger paths to match your ruling file locations

See `example-workflow.yml` for a reference implementation.

## Development

### Running Tests

```bash
cd .github/actions/ruling-diff-comment
uv run python -m unittest discover -v -s . -p "test_ruling_diff.py"
```

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
