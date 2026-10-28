# Ruling Diff Enhancer

Experimental local AI-assisted triage of the Markdown produced by
`ruling-diff-comment`. It does not post comments, create PRs, modify analyzer
files, or run analyzer tests.

## Inspect Inputs Without a Model

```bash
python3 ruling-diff-enhancer/enhance.py ~/git/sonar-java/ruling-comment.md \
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
python3 ruling-diff-enhancer/enhance.py /path/to/comment.md \
  --repo /path/to/analyzer --sonarpedia path/to/sonarpedia.json --prepare-only
```

The initial implementation supports the `S<digits>.html` / `S<digits>.json`
filename convention used by the Java checkout. Missing, invalid, or ambiguous
metadata is an error, not a reason to guess a specification.

## Review With DSPy

Requires Python 3.10+, `uv`, and an explicitly selected model accessible through
DSPy/LiteLLM. Set the selected provider's usual credential environment variables;
do not put tokens in arguments, source files, or comments. Use a model/provider
approved for the source code being reviewed. The HTML, JSON, and visible code
snippets are sent to that provider; this may incur charges.

```bash
uv sync --project ruling-diff-enhancer --frozen
export DSPY_MODEL='provider/model'
uv run --frozen --project ruling-diff-enhancer python ruling-diff-enhancer/enhance.py \
  ~/git/sonar-java/ruling-comment.md --repo ~/git/sonar-java \
  --output /tmp/ruling-review.md
```

Alternatively pass `--model provider/model`. `--api-base` (or `DSPY_API_BASE`)
supports custom endpoints, including local models. DSPy caching is disabled to
avoid persisting source snippets in its local cache. Provider-side logging and
retention remain subject to that provider's policy. `--format json` produces a
machine-readable report instead of Markdown.

One typed `dspy.Predict` call is made per rule/repository, merging examples from
multiple projects of the same rule. It prioritizes:

- Added issues that look like **false positives**.
- Removed issues that look like **lost true positives**.
- Otherwise, **one representative example**, not a fabricated regression.

`--max-examples` limits bad-case selections per rule (default: 3). Each selection
includes its original snippet, location, classification, and a short rationale.
Unknown/duplicate IDs, impossible change-kind classifications, and mixed
representative/bad-case selections are rejected.

Each rule also receives an overall summary, an opinion on the scale
`very_negative`, `negative`, `neutral`, `positive`, and confidence `low`, `medium`,
or `high`. These are subjective triage judgments, not calibrated probabilities
or proof of correctness. A change with no visible snippets must use low
confidence and selects no examples.

Only examples already present in the comment can be selected. The producer caps
snippets and can truncate whole rule sections. Missing context, source files,
unseen examples, and line moves limit what can be inferred; human review is still
required. The enhancer never retrieves additional source context or follows
instructions embedded in rule descriptions or snippets.

## Tests

```bash
uv run --frozen --project ruling-diff-enhancer python -m unittest discover \
  -s ruling-diff-enhancer -p 'test_*.py' -v
```

Tests use temporary metadata repositories, mocked predictions, and a DSPy dummy
language model. They require neither credentials nor paid/external model calls.
