# PVF Comment Parser

Parse `/pvf` activation comments from PR text into GitHub Action outputs.

## Usage

```yaml
- name: Parse /pvf comment
  id: pvf
  uses: SonarSource/core-languages-tooling-public/pvf-comment@master
  with:
    comment: ${{ github.event.comment.body }}
```

## Inputs

| Input | Description | Required |
|-------|-------------|----------|
| `comment` | PR description or comment body to scan for `/pvf` commands | Yes |
| `rule-prefixes` | Space-separated literal prefixes for rule keys (e.g. `"S M23_"`); defaults to `S` | No |

## Rule Keys

Rule keys match a configured prefix followed by one or more digits, optionally
followed by dot-separated digit segments. Matching is case-insensitive and covers
the entire token. Recognized keys are emitted in uppercase, in input order, as
comma-separated `rules-request` values and are not included in `languages`.
Prefixes are literal strings, not regular expressions.

For example, callers can enable MISRA keys with:

```yaml
    rule-prefixes: 'S M23_ MC-2012_ MC-2023_ MC-2025_ MC-AMD1_ MC-AMD2_ MC-AMD3_'
```

With those prefixes, `/pvf MC-2012_17.3 MC-AMD1_17.3` produces
`rules-request=MC-2012_17.3,MC-AMD1_17.3` and `languages=[]`.
Existing keys such as `S123` and `M23_042` remain valid. Dotted suffixes are
accepted for every configured prefix, not only MISRA prefixes.

Unrecognized tokens retain their original spelling in `languages`, including
unconfigured rule prefixes and malformed suffixes such as `MC-2012_17.`,
`MC-2012_17..3`, or `MC-2012_17.3x`. Signed and underscore-separated suffixes
(previously accepted by integer parsing) are no longer recognized as rule keys.

Flag behavior is unchanged: `all`, `ALL`, or `*` clears the requested rules;
`fps` or `FPS` enables FPS. A bare `/pvf`, or a command with no recognized rules,
requests all rules. Other flag casing is treated as language tokens.

## Outputs

| Output | Description |
|--------|-------------|
| `found` | `true` when a `/pvf` command was found; callers should skip PVF when `false` |
| `rules-request` | Rule keys for PVF `rules-request` when `found=true`; empty means all rules (e.g. bare `/pvf` or `/pvf all`) |
| `fps` | Whether the `fps` flag was present |
| `languages` | JSON array of language tokens from the comment |

## Requirements

- Python 3.10+ on the runner (`python3`, stdlib only)

See `example-workflow.yml` for a full caller workflow.
