#!/usr/bin/env bash
# Posts a message to Slack via the chat.postMessage Web API directly - no third-party
# action. rtCamp/action-slack-notify (the previous implementation) is a Docker container
# action, which the in-house EKS-backed runners (sonar-xs/s/m/l/xl) can't run at all
# (no Docker-in-Docker); this has no such requirement and runs anywhere.
#
# Expects env vars: SLACK_TOKEN, SLACK_CHANNEL, SLACK_MESSAGE.
#
# chat.postMessage always returns HTTP 200, even on failure - the real result is the
# "ok" field in the JSON body, so that's what determines this step's exit code.
set -uo pipefail

payload=$(jq -n --arg channel "$SLACK_CHANNEL" --arg text "$SLACK_MESSAGE" '{channel: $channel, text: $text}')

response=$(curl -sS -X POST https://slack.com/api/chat.postMessage \
  -H "Authorization: Bearer $SLACK_TOKEN" \
  -H "Content-Type: application/json; charset=utf-8" \
  --data "$payload")

if [[ "$(jq -r '.ok' <<<"$response")" != "true" ]]; then
  echo "::error title=Slack post failed::$(jq -r '.error // "unknown error"' <<<"$response")" >&2
  exit 1
fi

echo "Message posted to Slack channel: $SLACK_CHANNEL"
