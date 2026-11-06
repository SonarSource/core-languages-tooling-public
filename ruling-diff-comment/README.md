# Ruling Diff Comment Action

This GitHub Action analyzes changes in ruling expectations, stored in SARIF format, and posts a human-readable summary as a PR comment.

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
- When the optional enhancer is enabled, the workflow must supply
  `UV_INDEX_REPOX_USERNAME` and `UV_INDEX_REPOX_PASSWORD` to the action step
  so uv can download its locked packages from repox. The base action has no
  package dependencies and needs no repox credentials. For SonarSource CI,
  grant `id-token: write`, retrieve the
  `{REPO_OWNER_NAME_DASH}-private-reader` Artifactory token with
  `SonarSource/vault-action-wrapper@v3`, and set the username to an empty string
  and the password to the retrieved token. See [example-workflow.yml](example-workflow.yml).
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

Snippets for both added and removed issues use source files from the current
checkout, not from the base or head revision. Only the ruling report comparison
is revision-based. Initialize the required source submodules in the calling
workflow; the action does not fetch source content. Missing files produce a
placeholder snippet.

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

### Previewing Real Ruling Changes Locally

Use the same entry point as the action with `--dry-run` to generate the comment
without posting to GitHub. PR number, repository, and GitHub credentials are not
required in this mode. Python 3.10+ is sufficient; there are no package dependencies.

```bash
cd /path/to/analyzer-checkout
python3 /path/to/core-languages-tooling-public/ruling-diff-comment/ \
  --dry-run \
  --base-sha HEAD~1 \
  --head-sha HEAD \
  --sources-root its/sources \
  > /tmp/ruling-comment.md
```

Open `/tmp/ruling-comment.md` in a Markdown previewer to inspect the result.
Markdown goes to stdout; diagnostic logging goes to stderr. If there are no
changed ruling SARIF files or no issue deltas, stdout is empty.

Use `--output-file /tmp/ruling-comment.md` instead of `--dry-run` to write the
comment directly to a file. This also needs no PR context and writes an empty
file when there are no issue deltas. The file must be inside the current checkout,
the system temporary directory, or `/tmp`. The two preview options cannot be combined.

Run from the analyzer repository root. Both revisions must exist locally, and
the comparison uses Git's three-dot diff (`base...head`), just like the action.
Uncommitted expectations and generated `target/actual` or `build/actual` files
are not compared: for freshly generated results, sync them into expectations
in a disposable checkout and make a local-only commit first. No push is needed.

Set `--sources-root` to the analyzer's source location (for example,
`its/sources` or `private/its/sources`). Sources and any required submodule
commits should be available locally for snippets; missing submodule content can
trigger a Git fetch. Optional `--ruling-root` overrides the standard expected
directories. SARIF per-rule files are supported, including added and deleted
files; legacy JSON reports are ignored. SARIF results are compared by primary
source file, range coordinates, and issue message. Duplicate findings are
ignored; secondary locations do not participate in comparison.

Without a preview option, the existing posting behavior is unchanged and
`--pr-number` and `--repository` are required.

### AI-Assisted Diff Review

The optional [`ruling_diff_enhancer`](ruling_diff_enhancer) submodule reviews
the generated Markdown against local rule metadata using LiteLLM. The diff-comment
script automatically includes an automated review when `DSPY_MODEL` and a
Portkey API key are set. A linked **Rule overview** table shows
each rule's projects, removed/added counts, assessment, and plain-text confidence.
Rules are ordered by assessment, with negative assessments first. Each rule has
one section combining its summary and collapsible source examples across projects;
Selected examples appear first across all projects, with rationales beside their
original snippets and no duplicated code. The review prefers one selected example
per rule; at most three are allowed, and additional selections must demonstrate
materially different cases.
This applies both to `--dry-run` previews and posted PR comments. The existing
per-file and per-rule snippet limits still apply, and the review shares the
comment size budget with the rule details.

Reviews use OpenAI models, always through Portkey. Set `PORTKEY_API_KEY_OPENAI`
(or the generic `PORTKEY_API_KEY`) as described in the
[enhancer documentation](ruling_diff_enhancer).
The request includes rule HTML and JSON metadata, the repository and rule key,
changed finding locations and messages, and the source snippets visible in the
diff comment. Enable it only for repositories and source content approved for
sharing with Portkey and OpenAI. In particular, obtain the applicable data-sharing
approval before enabling it for proprietary analyzer code. Human reviewers remain
responsible for interpreting the assessment.
Without a model or key, the ordinary comment is unchanged and LiteLLM is
not imported. Enhancer errors (including missing dependencies or metadata) emit
a warning to stderr and preserve the original comment rather than blocking it.

To test locally, export your key using your normal secret-management mechanism,
and set `UV_INDEX_REPOX_USERNAME` and `UV_INDEX_REPOX_PASSWORD` to repox
package-download credentials for a cold-cache enhancer install,
then run from an analyzer checkout with committed SARIF expectation changes:

```bash
tooling=/path/to/core-languages-tooling-public/ruling-diff-comment
export DSPY_MODEL=gpt-4.1
uv run --project "$tooling" --frozen --extra enhancer python "$tooling/" \
  --dry-run --base-sha origin/master --head-sha HEAD \
  --sources-root its/sources > /tmp/ruling-comment.md
```

Adjust the revisions and sources root for the analyzer. The checkout needs
`sonarpedia.json` and the referenced `<rule>.html` / `<rule>.json` metadata pairs.
Open `/tmp/ruling-comment.md` to see the combined review and original snippets.
This preview does not post to GitHub, but **does call the configured model**:
rule metadata and visible source snippets leave your machine and charges may
apply. Use an approved model for the code being reviewed. Unset
`DSPY_MODEL` to preview the ordinary comment without making model calls.

The GitHub Action installs enhancer dependencies when `DSPY_MODEL` is set;
provide it and the API key through the calling workflow's environment. Ordinary
diff generation does not require AI dependencies.

### Running Tests

```bash
cd ruling-diff-comment
uv run --extra enhancer python -m unittest discover -v -s . -p "test_*.py"
```

For a cold-cache enhancer install, set `UV_INDEX_REPOX_USERNAME` and
`UV_INDEX_REPOX_PASSWORD` to repox package-download credentials before this
command. The tests use mocks and make no paid model calls. The base action
requires no repox credentials.

The tests cover CLI validation and preview/posting behavior, plus an integration
test that renders real ruling changes from a temporary local Git repository.
GitHub interactions are tested with mocks rather than creating real PRs.

### Project Structure

- `action.yml` - Action metadata and workflow steps
- `__main__.py` - Directory CLI entry point, reusing `ruling_diff.py`
- `ruling_diff.py` - Main entry point
- `ruling_diff_io.py` - Git and GitHub API interactions
- `ruling_diff_core.py` - Core module exports
- `ruling_diff_core_lib/` - Core logic modules
  - `models_and_constants.py` - Data models and configuration
  - `ruling_diff_logic.py` - Diff computation logic
  - `sarif.py` - SARIF report parsing
  - `snippet_generation.py` - Code snippet rendering
  - `comment_rendering.py` - Markdown comment formatting
- `ruling_diff_enhancer/` - Optional AI-assisted diff review
- `test_enhancer.py` and `test_models.py` - Enhancer input, model, and transport tests
- `test_ruling_diff.py` - Discovery, comparison, snippets, and GitHub interaction tests
- `test_sarif_diff.py` - SARIF parsing, range comparison, and Git integration tests

## License

See the LICENSE file in the repository root.
