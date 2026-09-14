# Prepare PVF

Composite action that records the candidate plugin version for PVF runs.

It writes the value of `build-version` to `candidate-version.txt` and uploads it as the
`candidate-version` artifact. The [`pvf-trigger`](../pvf-trigger) action later downloads this artifact
from the Build run to resolve the version to validate.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `build-version` | Candidate plugin build version to record for PVF validation | Yes | |
