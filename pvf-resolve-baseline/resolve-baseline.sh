#!/usr/bin/env bash
# Resolves the PVF baseline of a push to the default branch, see action.yml for the inputs.
# Writes baseline-version and baseline-sha, or skip-reason, to $GITHUB_OUTPUT.
set -euo pipefail

output() {
  echo "$1=$2" >> "$GITHUB_OUTPUT"
}

# Calls the GitHub API, retrying a failed call (5xx, rate limit) twice before giving up.
# On an HTTP error gh prints the error body on stdout, so it is only printed on success.
api() {
  local attempt response
  for attempt in 1 2 3; do
    if response="$(gh api "$@" 2>/dev/null)"; then
      printf '%s\n' "$response"
      return 0
    fi
    echo "GitHub API call failed (attempt ${attempt}/3): $1" >&2
    if [[ "$attempt" -lt 3 ]]; then
      sleep 10
    fi
  done
  return 1
}

skip() {
  local reason="$1" message="$2"
  echo "::notice::${message}, skipping performance validation."
  output skip-reason "$reason"
  exit 0
}

# The merged PR opts out with the skip-pvf label or [skip pvf] in its title.
if pr="$(api "repos/${GITHUB_REPOSITORY}/commits/${CURRENT_SHA}/pulls" --jq '[.[] | select(.merged_at != null)][0] // {}')"; then
  if [[ "$(jq 'any(.labels[]?; .name == "skip-pvf") or ((.title // "") | contains("[skip pvf]"))' <<<"$pr")" = "true" ]]; then
    skip opt-out "PR #$(jq -r '.number' <<<"$pr") has the skip-pvf label or [skip pvf] in its title"
  fi
else
  echo "::warning::Could not look up the PR merged by ${CURRENT_SHA}, so its skip-pvf opt-out is ignored."
fi

# The previous commit is empty or all zeros when the push created the branch.
has_previous=false
if [[ -n "${PREVIOUS_SHA//0/}" ]]; then
  has_previous=true
fi

# A push changing only files that match skip-paths needs no validation. The compare API lists at
# most 300 files, so a longer list may be incomplete and is never skipped.
if [[ -n "$SKIP_PATHS" ]] && [[ "$has_previous" = true ]]; then
  if files="$(api "repos/${GITHUB_REPOSITORY}/compare/${PREVIOUS_SHA}...${CURRENT_SHA}" --jq '.files[].filename')"; then
    if [[ -n "$files" ]] && [[ "$(wc -l <<<"$files")" -lt 300 ]] && ! grep -qvE "$SKIP_PATHS" <<<"$files"; then
      skip skip-paths "Every file changed by the push matches skip-paths"
    fi
  else
    echo "::warning::Could not list the files changed by the push, so skip-paths is ignored."
  fi
fi

# Prints the plugin version that prepare-pvf recorded in a Build run, or nothing.
recorded_version() {
  local run_id="$1" dir
  dir="$(mktemp -d)"
  if gh run download "$run_id" --repo "$GITHUB_REPOSITORY" --name candidate-version --dir "$dir" >/dev/null 2>&1 \
    && [[ -s "$dir/candidate-version.txt" ]]; then
    tr -d '[:space:]' < "$dir/candidate-version.txt"
  fi
  rm -rf "$dir"
}

# Prints "done" once the run can no longer record a version: the run completed, or the publication
# job finished, whatever its conclusion (a skipped job counts as finished). Prints "waiting"
# otherwise, including when the API fails, so the next poll retries.
publication_state() {
  local run_id="$1" status jobs
  if ! status="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}" --jq '.status' 2>/dev/null)"; then
    echo waiting
    return
  fi
  if [[ "$status" = "completed" ]]; then
    echo done
    return
  fi
  if [[ -z "$PUBLICATION_JOB" ]]; then
    echo waiting
    return
  fi
  if ! jobs="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}/jobs?per_page=100" 2>/dev/null)"; then
    echo waiting
    return
  fi
  # A job whose dependencies are still running is not listed yet.
  if [[ "$(jq -r --arg name "$PUBLICATION_JOB" '[.jobs[] | select(.name == $name)][0].status // "pending"' <<<"$jobs")" = "completed" ]]; then
    echo done
  else
    echo waiting
  fi
}

# One deadline shared by every run of the previous commit.
wait_deadline=$((SECONDS + WAIT_MINUTES * 60))

# Like recorded_version, but waits while the run can still record a version: falling back would
# silently compare across several merges.
awaited_version() {
  local run_id="$1" version
  while :; do
    version="$(recorded_version "$run_id")"
    if [[ -n "$version" ]]; then
      echo "$version"
      return
    fi
    if [[ "$(publication_state "$run_id")" = "done" ]]; then
      # The artifact may have been uploaded just before the job finished.
      recorded_version "$run_id"
      return
    fi
    if [[ "$SECONDS" -ge "$wait_deadline" ]]; then
      echo "Gave up waiting for run ${run_id} to record its plugin version" >&2
      return
    fi
    echo "Waiting for run ${run_id} to record its plugin version" >&2
    sleep 60
  done
}

found() {
  local version="$1" run_id="$2" sha="$3"
  echo "Baseline ${version} built from ${sha} in ${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${run_id}"
  output baseline-version "$version"
  output baseline-sha "$sha"
  exit 0
}

runs="repos/${GITHUB_REPOSITORY}/actions/workflows/${BUILD_WORKFLOW}/runs"
if [[ "$has_previous" = true ]]; then
  if ! previous_runs="$(api "${runs}?head_sha=${PREVIOUS_SHA}&branch=${BRANCH}&event=push&per_page=10" --jq '.workflow_runs[].id')"; then
    echo "::error::Could not list the ${BUILD_WORKFLOW} runs of ${PREVIOUS_SHA}."
    exit 1
  fi
  for run_id in $previous_runs; do
    version="$(awaited_version "$run_id")"
    if [[ -n "$version" ]]; then
      found "$version" "$run_id" "$PREVIOUS_SHA"
    fi
  done
fi

# Fallback: earlier builds, newest first, e.g. when the previous commit's build failed before it
# deployed the plugin. The comparison then spans several merges.
if ! created_at="$(api "repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}" --jq '.created_at')" \
  || ! earlier="$(api "${runs}?branch=${BRANCH}&event=push&per_page=30")"; then
  echo "::error::Could not list the earlier ${BUILD_WORKFLOW} runs on ${BRANCH}."
  exit 1
fi
earlier_runs="$(jq -r --arg sha "$CURRENT_SHA" --arg before "$created_at" \
  '.workflow_runs[] | select(.head_sha != $sha and .created_at < $before) | "\(.id):\(.head_sha)"' <<<"$earlier")"
for run in $earlier_runs; do
  version="$(recorded_version "${run%%:*}")"
  if [[ -n "$version" ]]; then
    found "$version" "${run%%:*}" "${run#*:}"
  fi
done

echo "::warning::No earlier ${BUILD_WORKFLOW} run on ${BRANCH} recorded a plugin version, skipping performance validation."
output skip-reason no-baseline
