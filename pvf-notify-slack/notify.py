"""Build the PVF alert Markdown, including the commits since the baseline."""

import json
import os
import re
import secrets
import subprocess
from urllib.parse import quote

MAX_COMMITS = 20
MAX_TITLE = 200

# Slack syntax is neutralized with lookalikes: the shared Markdown converter removes backslash escapes.
LOOKALIKES = str.maketrans({"&": "＆", "<": "‹", ">": "›", "*": "∗", "_": "＿", "`": "ˋ", "~": "∼"})
MARKDOWN_SYNTAX = re.compile(r"[\[\]\\{}()!#|]")


def literal(text):
    return MARKDOWN_SYNTAX.sub(r"\\\g<0>", str(text).translate(LOOKALIKES))


def link_target(url):
    return quote(url, safe=":/?&=#%@+,;~!$'*[]")


def commits_since(repository, baseline, head):
    """Newest-first commits up to the baseline, and whether the baseline was reached."""
    result = subprocess.run(
        ["gh", "api", f"repos/{repository}/commits?sha={head}&per_page={MAX_COMMITS + 1}"],
        capture_output=True, text=True, check=True)
    commits = []
    for commit in json.loads(result.stdout):
        if commit["sha"] == baseline:
            return commits, True
        commits.append(commit)
    return commits[:MAX_COMMITS], False


def commit_section(env):
    if not env["BASE_SHA"]:
        return []
    repository, base, head = env["REPOSITORY"], env["BASE_SHA"], env["HEAD_SHA"]
    try:
        commits, complete = commits_since(repository, base, head)
    except (subprocess.CalledProcessError, ValueError, KeyError):
        print("::warning::Commit range lookup failed; sending PVF alert without commits")
        return ["Commit range unavailable."]
    lines = ["Commits:"]
    for commit in commits:
        author = (commit.get("author") or {}).get("login") or "unknown"
        title = commit["commit"]["message"].split("\n")[0][:MAX_TITLE]
        lines.append(f"{literal(commit['sha'][:8])} {literal(title)} (@{literal(author)})")
    if not complete:
        compare = f"{env['SERVER_URL']}/{repository}/compare/{base}...{head}"
        lines.append(f"… and more: [full range]({link_target(compare)})")
    return lines


def summary(env):
    result, baseline_result = env["VALIDATION_RESULT"], env["BASELINE_RESULT"]
    if result == "skipped":
        if baseline_result == "success" and not env["BASE_SHA"]:
            return "was skipped.", ["No baseline version was found in previous builds."]
        return "was skipped.", [f"Baseline resolution: {literal(baseline_result)}."]
    if result not in ("success", "failure"):
        raise ValueError("Unsupported validation outcome")
    lines = ["The validation job failed before completing."] if result == "failure" else []
    if env["REGRESSED_PROJECTS"]:
        lines.append(f"Regressed: {literal(env['REGRESSED_PROJECTS'])}")
    if env["ERRORED_PROJECTS"]:
        lines.append(f"Errored: {literal(env['ERRORED_PROJECTS'])}")
    if result == "success":
        lines.append(f"New/lost issues: {literal(env['NEW_ISSUES'] or 0)} / {literal(env['LOST_ISSUES'] or 0)}")
    return "reported problems.", lines


def message(env):
    outcome, details = summary(env)
    lines = [f"⚠️ **Performance Validation** on {literal(env['BRANCH'])} "
             f"({literal(env['HEAD_SHA'][:8])}) {outcome}", *details]
    lines.append(f"Triggered by: {literal(env['ACTOR'] or 'unknown')}")
    lines.extend(commit_section(env))
    links = [f"[Run logs]({link_target(env['RUN_URL'])})"]
    if env["DASHBOARD_URL"]:
        links.insert(0, f"[Dashboard]({link_target(env['DASHBOARD_URL'])})")
    lines.append(" · ".join(links))
    return "\n".join(lines)


def main():
    try:
        text = message(os.environ)
    except ValueError as error:
        print(f"::error::{error}")
        return 1
    # A random delimiter keeps repository-controlled text from injecting action outputs.
    delimiter = f"pvf_{secrets.token_hex(16)}"
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"markdown<<{delimiter}\n{text}\n{delimiter}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
