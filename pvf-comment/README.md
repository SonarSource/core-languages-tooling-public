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

## Outputs

| Output | Description |
|--------|-------------|
| `found` | `true` when a `/pvf` command was found; callers should skip PVF when `false` |
| `payload` | JSON object with `rules`, `languages`, `fps`, and `all_flag` |
| `rules-request` | Rule keys for PVF `rules-request` when `found=true`; empty means all rules (e.g. bare `/pvf` or `/pvf all`) |
| `fps` | Whether the `fps` flag was present |
| `languages` | JSON array of language tokens from the comment |

## Requirements

- Python 3.10+ on the runner (`python3`, stdlib only)

See `example-workflow.yml` for a full caller workflow.
