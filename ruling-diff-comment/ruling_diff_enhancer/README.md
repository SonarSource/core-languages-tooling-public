# Ruling Diff Enhancer

Experimental local AI-assisted triage of the Markdown produced by
`ruling-diff-comment`. It does not post comments, create PRs, modify analyzer
files, or run analyzer tests. It is a submodule of `ruling-diff-comment`.

Run the commands below from the `ruling-diff-comment` directory.

## Inspect Inputs Without a Model

```bash
python3 -m ruling_diff_enhancer ~/git/sonar-java/ruling-comment.md \
  --repo ~/git/sonar-java --prepare-only > /tmp/ruling-review-inputs.json
```

This standard-library-only mode extracts rule keys (for example `S9149`), rule
repositories, project names, issue counts, and visible added/removed snippets.
It recursively discovers `sonarpedia.json` under the analyzer checkout, resolves
`rules-metadata-path` relative to each configuration, and loads the corresponding
`S9149.html` and `S9149.json` files locally. It makes no network or model calls.
Metadata paths must stay within the analyzer repository.

If more than one configuration supplies the same rule, select one explicitly:

```bash
python3 -m ruling_diff_enhancer /path/to/comment.md \
  --repo /path/to/analyzer --sonarpedia path/to/sonarpedia.json --prepare-only
```

The initial implementation supports the `S<digits>.html` / `S<digits>.json`
filename convention used by the Java checkout. Missing, invalid, or ambiguous
metadata is an error, not a reason to guess a specification.

## Review With LiteLLM

The diff-comment creation script can also invoke this enhancer automatically
and include its review in the final comment. See the parent README's
[AI-assisted diff review](../README.md#ai-assisted-diff-review) section for
credential configuration and a one-command local preview.

Requires Python 3.10+, `uv`, and an explicitly selected model accessible through
LiteLLM. Set the selected provider's usual credential environment variables;
do not put tokens in arguments, source files, or comments. Use a model/provider
approved for the source code being reviewed. The HTML, JSON, and visible code
snippets are sent to that provider; this may incur charges.

```bash
uv sync --extra enhancer --frozen
export DSPY_MODEL='provider/model'
uv run --frozen --extra enhancer python -m ruling_diff_enhancer \
  ~/git/sonar-java/ruling-comment.md --repo ~/git/sonar-java \
  --output /tmp/ruling-review.md
```

Alternatively pass `--model provider/model`. `--provider direct` forces the
existing direct LiteLLM connection even if Portkey keys are present.
`--api-base` (or `DSPY_API_BASE`) supports custom endpoints, including local
models. The enhancer does not cache source snippets locally. Provider-side
logging and retention remain subject to that provider's policy. `--format json` produces a machine-readable report instead
of Markdown.

### Portkey for Local Testing

Following `rule-identification`, the default `--provider auto` selects Portkey
for a supported model family only when a matching Portkey key is available and
no `--api-base`/`DSPY_API_BASE` custom endpoint was supplied; otherwise it uses
the direct provider. No underlying provider API key is
required in Portkey mode. Export your key as `PORTKEY_API_KEY` using your
usual secret-management mechanism, then run:

```bash
uv run --frozen --extra enhancer python -m ruling_diff_enhancer \
  ~/git/sonar-java/ruling-comment.md --repo ~/git/sonar-java \
  --provider portkey --model claude-sonnet-4-5-20250929 \
  --output /tmp/ruling-review.md
```

Select a model enabled for your Portkey key. Both bare names (as above) and
prefixed names such as `anthropic/claude-sonnet-4-5-20250929` are accepted.
Supported Portkey model families are GPT/o-series, Claude, and Gemini. Claude
uses the native Anthropic transport; GPT/o-series and Gemini use Portkey's
OpenAI-compatible transport, with the appropriate provider routing header.

Family-specific keys take precedence over the generic `PORTKEY_API_KEY`:

| Model family | Preferred environment variable |
| --- | --- |
| GPT / o-series | `PORTKEY_API_KEY_OPENAI` |
| Claude | `PORTKEY_API_KEY_CLAUDE` |
| Gemini | `PORTKEY_API_KEY_GOOGLE` |

`DSPY_PROVIDER` supplies the default connection mode (`auto`, `direct`, or
`portkey`). Explicit `--provider portkey` fails early if the selected model has
no matching key; it does not silently fall back to a direct provider.
Unknown/custom model families retain direct `provider/model` routing in auto
mode. `--api-base` uses the direct provider in auto mode, so custom/local
endpoints retain their own credentials even when Portkey keys are present. Use
explicit `--provider portkey --api-base ...` to opt in to a custom Portkey
gateway. Portkey mode sends the same review evidence through Portkey to the
selected provider, so its logging, access controls, and retention policies also
apply.

## Review Results

One structured LiteLLM call is made per rule/repository, merging examples from
multiple projects of the same rule. It prioritizes:

- Added issues that look like **false positives**.
- Removed issues that look like **lost true positives**.
- Otherwise, **one representative example**, not a fabricated regression.

`--max-examples` limits bad-case selections per rule (1–3, default upper bound: 3).
The predictor is instructed to prefer one strongest example and select more only
for materially different failure modes or rule exceptions, not merely different
files, projects, or names. Additional rationales must explain the distinct case.
Each selection includes its original snippet, location, classification, and a
short rationale. The integrated comment displays all selected examples before
unselected source examples, including when they come from different projects.
Unknown/duplicate IDs, impossible change-kind classifications, and mixed
representative/bad-case selections are rejected.

Each rule also receives an overall summary, an opinion on the scale
`very_negative`, `negative`, `neutral`, `positive`, and confidence `low`, `medium`,
or `high`. These are subjective triage judgments, not calibrated probabilities
or proof of correctness. A change with no visible snippets must use low
confidence and selects no examples.

In combined diff comments, a linked overview table leads to one section per
rule/repository, grouping projects and their source examples. Selected rationales
appear with the original snippets rather than repeating them in a separate review.
Color indicates the opinion only; confidence is displayed as neutral text.

Only examples already present in the comment can be selected. The producer caps
snippets and can truncate whole rule sections. Missing context, source files,
unseen examples, and line moves limit what can be inferred; human review is still
required. The enhancer never retrieves additional source context or follows
instructions embedded in rule descriptions or snippets.

## Tests

```bash
uv run --frozen --extra enhancer python -m unittest -v test_enhancer test_models
```

Tests use temporary metadata repositories, mocked predictions, and mocked HTTP
requests for the actual Portkey transports.
They require neither credentials nor paid/external model calls.
