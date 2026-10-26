#!/usr/bin/env bash
# Posts a message to Slack via the chat.postMessage Web API directly - no third-party
# action, and no jq dependency (check-run-details.sh's jq-less fallback path must still
# be able to deliver its message even when jq isn't on the runner).
#
# Expects env vars: SLACK_TOKEN, SLACK_CHANNEL, SLACK_MESSAGE.
# SLACK_CHANNEL is a comma-separated list of one or more channels; the message is posted
# to each independently so one bad channel doesn't suppress delivery to the others.
#
# chat.postMessage always returns HTTP 200, even on failure - success is checked via
# plain string matching on the "ok" field in the response body, not jq.
set -uo pipefail

failed=false
IFS=',' read -ra channels <<< "$SLACK_CHANNEL"
for channel in "${channels[@]}"; do
  channel="$(echo "$channel" | xargs)" # trim whitespace
  [[ -z "$channel" ]] && continue

  response=$(curl -sS -X POST https://slack.com/api/chat.postMessage \
    -H "Authorization: Bearer $SLACK_TOKEN" \
    -H "Content-Type: application/x-www-form-urlencoded; charset=utf-8" \
    --data-urlencode "channel=$channel" \
    --data-urlencode "text=$SLACK_MESSAGE")

  if [[ "$response" != *'"ok":true'* ]]; then
    echo "::error title=Slack post failed::channel $channel: ${response:-no response from Slack (curl failed)}" >&2
    failed=true
    continue
  fi

  echo "Message posted to Slack channel: $channel"
done

[[ "$failed" == true ]] && exit 1
exit 0
