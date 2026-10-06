"""Send a PVF alert with best-effort commit and merger attribution."""
from __future__ import annotations

import html
import json
import os
import subprocess
import urllib.request


def escape(value):
    # Prevent repository-controlled content from creating mentions or Slack formatting.
    return html.escape(str(value), quote=False).replace("*", "∗").replace("_", "＿").replace("`", "ˋ").replace("~", "∼")


def api(repository, path):
    result = subprocess.run(["gh", "api", f"repos/{repository}/{path}"],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def attribution(settings):
    fallback = settings.get("MERGER") or "unknown"
    if not settings.get("BASE_SHA"):
        return [], 0, [fallback], False
    repository = settings["REPOSITORY"]
    try:
        compare = api(repository, f"compare/{settings['BASE_SHA']}...{settings['HEAD_SHA']}?per_page=100&page=1")
        total = compare["total_commits"]
        # The compare endpoint returns chronological commits. Fetch the final pages only.
        last_page = max(1, (total + 99) // 100)
        commits = compare["commits"] if last_page == 1 else api(
            repository, f"compare/{settings['BASE_SHA']}...{settings['HEAD_SHA']}?per_page=100&page={last_page}"
        )["commits"]
        if len(commits) < 20 and last_page > 1:
            prior = compare["commits"] if last_page == 2 else api(
                repository, f"compare/{settings['BASE_SHA']}...{settings['HEAD_SHA']}?per_page=100&page={last_page - 1}"
            )["commits"]
            commits = prior + commits
        commits = commits[-20:]
    except (subprocess.CalledProcessError, ValueError, KeyError):
        print("::warning::Commit range lookup failed; sending PVF alert without commit attribution")
        return [], 0, [fallback], False
    mergers = []
    for commit in commits:
        who = (commit.get("author") or {}).get("login")
        try:
            pulls = api(repository, f"commits/{commit['sha']}/pulls")
            merged = [p for p in pulls if p.get("merged_at") and p["base"]["ref"] == settings["BRANCH"]]
            if merged:
                pull = api(repository, f"pulls/{merged[0]['number']}")
                who = (pull.get("merged_by") or {}).get("login") or who
        except (subprocess.CalledProcessError, ValueError, KeyError):
            print("::warning::Merger lookup failed for a commit; continuing PVF alert")
        if who and who not in mergers:
            mergers.append(who)
    return commits, total, mergers or [fallback], True


def slack_link(url, label):
    # Encode Slack link delimiters rather than allowing text to escape the link.
    safe = str(url).replace("|", "%7C").replace("<", "%3C").replace(">", "%3E").replace("\n", "%0A").replace("\r", "%0D")
    return f"<{html.escape(safe, quote=False)}|{label}>"


def message(settings, context):
    commits, total, mergers, available = context
    result = settings["VALIDATE_RESULT"]
    if result not in {"success", "failure", "skipped"}:
        raise ValueError("Unsupported validation outcome")
    heading = f"⚠️ *Performance Validation* on {escape(settings['BRANCH'])} ({escape(settings['HEAD_SHA'][:8])})"
    lines = [heading + (" was skipped." if result == "skipped" else " reported problems.")]
    if result == "skipped":
        lines.append("No baseline version could be resolved from previous builds." if settings["RESOLVE_RESULT"] == "success" else
                     f"Baseline resolution did not complete (resolve_baseline: {escape(settings['RESOLVE_RESULT'])}).")
    else:
        if result == "failure":
            lines.append("The validation job itself failed.")
        if settings.get("REGRESSED"):
            lines.append(f"Regressed: {escape(settings['REGRESSED'])}")
        if settings.get("ERRORED"):
            lines.append(f"Errored: {escape(settings['ERRORED'])}")
        if result == "success":
            lines.append(f"New/lost issues: {escape(settings.get('NEW') or '0')} / {escape(settings.get('LOST') or '0')}")
    lines.append("Mergers: " + ", ".join(escape(who) for who in mergers))
    if available:
        lines.append(f"Commits ({total}):")
        for commit in reversed(commits):
            title = commit["commit"]["message"].split("\n")[0][:200]
            author = (commit.get("author") or {}).get("login") or "unknown"
            lines.append(f"{escape(commit['sha'][:8])} {escape(title)} (@{escape(author)})")
        if total > 20:
            lines.append(f"… and {total - 20} more")
    else:
        lines.append("Commit range unavailable.")
    links = [slack_link(settings["RUN_URL"], "Run logs")]
    if settings.get("URL"):
        links.insert(0, slack_link(settings["URL"], "Dashboard"))
    lines.append(" · ".join(links))
    return "\n".join(lines)


def send(settings, text):
    payload = json.dumps({"text": text, "channel": settings["SLACK_CHANNEL"],
                          "username": settings["SLACK_USERNAME"], "link_names": False}).encode("utf-8")
    request = urllib.request.Request(settings["SLACK_WEBHOOK"], data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200 or response.read().strip() != b"ok":
            raise ValueError("Slack rejected the notification")


def main():
    try:
        send(os.environ, message(os.environ, attribution(os.environ)))
    except Exception as error:
        # Webhook URLs are credentials; never echo exception text or response bodies.
        print(f"::error::PVF Slack notification failed ({type(error).__name__}); check inputs and webhook access")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
