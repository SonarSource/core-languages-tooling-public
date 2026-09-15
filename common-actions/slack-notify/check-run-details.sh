#!/usr/bin/env bash
# Builds the Slack message body for the calling composite action.
# Expects env vars: GH_TOKEN, BRANCH, CONCLUSION, TITLE, SUCCESS_CONCLUSIONS_CSV,
# GITHUB_EVENT_PATH, GITHUB_OUTPUT, GITHUB_REPOSITORY, GITHUB_SERVER_URL (the last four
# are set automatically by the runner).
set -uo pipefail

if [[ -n "${CUSTOM_MESSAGE:-}" ]]; then
  summary="$CUSTOM_MESSAGE"
  failed_check_runs=""
  degraded=true # skip the check_suite/jq lookups below entirely
elif ! command -v jq >/dev/null 2>&1; then
  # No jq: don't pretend this is a manual test run - degrade with repo context.
  failed_check_runs="_(failed to read event payload: jq is not available on this runner)_"
  summary="Pipeline in [$GITHUB_REPOSITORY]($GITHUB_SERVER_URL/$GITHUB_REPOSITORY) failed ($CONCLUSION) on $BRANCH"
  check_runs_url=""
  degraded=true
else
  check_runs_url=$(jq -r '.check_suite.check_runs_url // empty' "$GITHUB_EVENT_PATH")
fi

if [[ "${degraded:-false}" == "true" ]]; then
  : # message already built above
elif [[ -n "$check_runs_url" ]]; then
  if check_runs=$(gh api --paginate --jq '.check_runs[]' "$check_runs_url" 2>/tmp/gh-api-error.log); then
    failed_check_runs=$(printf '%s\n' "$check_runs" | jq -r --arg success_csv "$SUCCESS_CONCLUSIONS_CSV" '
      ($success_csv | split(",") | map(gsub("^\\s+|\\s+$"; ""))) as $success
      | select(($success | index(.conclusion)) | not)
      | "* [\(.name)](\(.details_url))"
    ')
    [[ -z "$failed_check_runs" ]] && failed_check_runs="_(no failing check runs found)_"

    pipeline_name=$(jq -r '.check_suite.app.name // "Pipeline"' "$GITHUB_EVENT_PATH")
    repo_name=$(jq -r '.repository.name' "$GITHUB_EVENT_PATH")
    repo_url=$(jq -r '.repository.html_url' "$GITHUB_EVENT_PATH")
    commit_summary=$(jq -r '.check_suite.head_commit.message' "$GITHUB_EVENT_PATH" | head -n1)
    summary="$pipeline_name in [$repo_name]($repo_url) failed ($CONCLUSION) on $BRANCH: $commit_summary"
  else
    failed_check_runs="_(failed to fetch check run details: $(tr -s '\n' ' ' < /tmp/gh-api-error.log))_"
    summary="Pipeline in [$GITHUB_REPOSITORY]($GITHUB_SERVER_URL/$GITHUB_REPOSITORY) failed ($CONCLUSION) on $BRANCH"
  fi
else
  failed_check_runs="_(manual test run - no check run details available)_"
  summary="Manual test notification for branch $BRANCH (conclusion: $CONCLUSION)"
fi

delimiter="ghadelim_$(date +%s)_$RANDOM"
{
  echo "message<<$delimiter"
  echo "❌ *$TITLE*"
  echo "$summary"
  echo "$failed_check_runs"
  echo "$delimiter"
} >> "$GITHUB_OUTPUT"
