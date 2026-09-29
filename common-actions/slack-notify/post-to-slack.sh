#!/usr/bin/env bash
# Posts a message to Slack via the chat.postMessage Web API directly - no third-party
# action, and no jq dependency (check-run-details.sh's jq-less fallback path must still
# be able to deliver its message even when jq isn't on the runner).
#
# Expects env vars: SLACK_TOKEN, SLACK_CHANNEL, SLACK_MESSAGE.
#
# chat.postMessage always returns HTTP 200, even on failure - success is checked via
# plain string matching on the "ok" field in the response body, not jq.
set -uo pipefail

response=$(curl -sS -X POST https://slack.com/api/chat.postMessage \
  -H "Authorization: Bearer $SLACK_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded; charset=utf-8" \
  --data-urlencode "channel=$SLACK_CHANNEL" \
  --data-urlencode "text=$SLACK_MESSAGE")

if [[ "$response" != *'"ok":true'* ]]; then
  echo "::error title=Slack post failed::${response:-no response from Slack (curl failed)}" >&2
  exit 1
fi

echo "Message posted to Slack channel: $SLACK_CHANNEL"
