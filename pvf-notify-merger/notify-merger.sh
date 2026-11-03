#!/usr/bin/env bash
# Comments on the PR merged by a push whose PVF run found problems, see action.yml for the inputs.
set -euo pipefail

pr="$(gh api "repos/${REPO}/commits/${MERGED_SHA}/pulls" \
  --jq '[.[] | select(.merged_at != null)][0].number // empty')"
if [ -z "$pr" ]; then
  echo "::warning::No merged PR found for ${MERGED_SHA} in ${REPO}, nobody to notify."
  exit 0
fi
merger="$(gh api "repos/${REPO}/pulls/${pr}" --jq '.merged_by.login // .user.login')"

body="@${merger} ⚠️ **Performance Validation** of \`${MERGED_SHA:0:10}\` on master found problems after this PR was merged (baseline \`${BASELINE}\`, candidate \`${CANDIDATE}\`):"
if [ -n "$REGRESSED" ]; then
  body+=$'\n'"- 🐢 Regressed projects: ${REGRESSED}"
fi
if [ -n "$ERRORED" ]; then
  body+=$'\n'"- 💥 Errored projects: ${ERRORED}"
fi
if [ -n "$FAILED_JOBS" ]; then
  body+=$'\n'"- ❌ Failed jobs: ${FAILED_JOBS}"
fi
if [ -n "$BASELINE_SHA" ]; then
  body+=$'\n\n'"Compared with \`${BASELINE_SHA:0:10}\` ([changes](${GITHUB_SERVER_URL}/${REPO}/compare/${BASELINE_SHA}...${MERGED_SHA}))."
  if [ -n "$PREVIOUS_SHA" ] && [ "$BASELINE_SHA" != "$PREVIOUS_SHA" ]; then
    body+=" The previous commit had no usable build, so this covers several merges."
  fi
fi
links="[See run logs](${RUN_URL})"
if [ -n "$DASHBOARD_URL" ]; then
  links="[View dashboard](${DASHBOARD_URL}) · ${links}"
fi
body+=$'\n\n'"${links}"

gh pr comment "$pr" --repo "$REPO" --body "$body"
