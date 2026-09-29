#!/usr/bin/env bash
# Builds the Slack message: "❌ <name> in <repo> failed on <branch>: <commit>" + a bulleted
# failed-job list, for a job in the same workflow run whose failure is being reported.
set -uo pipefail

repo_url="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY"
repo_name="${GITHUB_REPOSITORY#*/}"

# Reads a stream of job objects (from the run-jobs API) on stdin, prints a bulleted list
# of the failed ones.
# Example:
# Input:
#   {"name":"build","status":"completed","conclusion":"success","html_url":"https://github.com/org/repo/actions/runs/1/jobs/1"}
#   {"name":"test","status":"completed","conclusion":"failure","html_url":"https://github.com/org/repo/actions/runs/1/jobs/2"}
# Output:
#   • <https://github.com/org/repo/actions/runs/1/jobs/2|test>
failed_jobs() {
  jq -r '
    def not_in(arr): . as $x | (arr | index($x)) == null;

    ["success", "neutral", "skipped"] as $success_conclusions
    | select(.status == "completed")
    | select(.conclusion | not_in($success_conclusions))
    | "• <\(.html_url)|\(.name)>"
  '
}

# status == "completed" excludes the calling job itself (still in_progress here).
summary="${WORKFLOW_NAME:-Pipeline} in <$repo_url|$repo_name> failed on $BRANCH: <$repo_url/commit/$GITHUB_SHA|${GITHUB_SHA:0:7}>"

if jobs=$(gh api --paginate "repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/jobs" --jq '.jobs[]' 2>/tmp/gh-api-error.log); then
  failed_list=$(printf '%s\n' "$jobs" | failed_jobs)
  [[ -z "$failed_list" ]] && failed_list="_(no failing jobs found)_"
else
  failed_list="_(failed to fetch job details: $(tr -s '\n' ' ' < /tmp/gh-api-error.log))_"
fi

delimiter="ghadelim_$(date +%s)_$RANDOM"
{
  echo "message<<$delimiter"
  echo "❌ $summary"
  [[ -n "$failed_list" ]] && echo "$failed_list"
  echo "$delimiter"
} >> "$GITHUB_OUTPUT"
