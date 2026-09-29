# Prepare Ruling Artifact Action

Packages generated ruling results as an `actual_*` artifact for
`ruling-update-and-notify`.

By default, the action finds either `its/ruling/target/actual` or
`private/its/ruling/target/actual`. It copies the contents under `expected/` in
the uploaded artifact, so a generated `project/xml-S123.json` becomes
`expected/project/xml-S123.json` when the notification action downloads it.
It fails if neither directory exists, both exist, or no JSON results are found.

```yaml
- name: Prepare ruling artifact
  if: ${{ always() && steps.ruling.outcome == 'failure' }}
  uses: SonarSource/core-languages-tooling-public/prepare-ruling-artifact@master
```

| Input | Required | Default | Purpose |
|-------|----------|---------|---------|
| `actual-root` | No | Auto-detected | Override the generated results directory for another layout. |
| `artifact-name` | No | `actual_ruling` | Use a distinct `actual_*` name when multiple jobs upload results. |

Run after the ruling test and before `ruling-update-and-notify` in the same
workflow run. The consumer merges all artifacts named `actual_*` into the
detected ruling resources directory.
