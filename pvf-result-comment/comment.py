"""Format and post PVF results, preserving the original action's defaults."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


def markdown(value):
    return re.sub(r"([\\`*_{}\[\]<>()!#|])", r"\\\1", str(value))


def link(url):
    return str(url).replace("\\", "%5C").replace("(", "%28").replace(")", "%29").replace("\n", "%0A").replace("\r", "%0D").replace(" ", "%20").replace("<", "%3C").replace(">", "%3E")


def body(settings):
    url = settings.get("URL", "")
    run_url = link(settings["RUN_URL"])
    outcome = settings.get("VALIDATE_RESULT", "")
    if not outcome:
        if not url:
            return f"⚠️ **Performance Validation** finished without publishing a dashboard. [See run logs]({run_url})."
        return ("📊 **Performance Validation** complete\n"
                f"🆕 {markdown(settings.get('NEW') or '0')} new · 🗑️ {markdown(settings.get('LOST') or '0')} lost issues\n"
                f"[View dashboard]({link(url)})")
    if outcome not in {"success", "failure", "skipped", "cancelled"}:
        raise ValueError("Unsupported validation outcome")
    regressed = settings.get("REGRESSED", "")
    errored = settings.get("ERRORED", "")
    if outcome == "skipped":
        lines = ["⏭️ **Performance Validation** skipped"]
    elif outcome == "cancelled":
        lines = ["⏹️ **Performance Validation** cancelled"]
    elif outcome == "failure" or regressed or errored:
        lines = ["⚠️ **Performance Validation** reported problems"]
    else:
        lines = ["📊 **Performance Validation** complete"]
    if settings.get("SHA"):
        lines[0] += f" on {markdown(settings['SHA'][:8])} ({markdown(settings.get('BRANCH') or 'default branch')})"
    if outcome == "skipped":
        lines.append(markdown(settings.get("SKIP_REASON") or "No baseline could be resolved."))
    elif outcome == "failure":
        lines.append("The validation job itself failed.")
    elif outcome == "success":
        lines.append(f"🆕 {markdown(settings.get('NEW') or '0')} new · 🗑️ {markdown(settings.get('LOST') or '0')} lost issues")
    if regressed:
        lines.append(f"Regressed: {markdown(regressed)}")
    if errored:
        lines.append(f"Errored: {markdown(errored)}")
    lines.append(f"[View dashboard]({link(url)}) · [Run logs]({run_url})" if url else
                 f"No dashboard was published. [Run logs]({run_url})")
    return "\n".join(lines)


def find_pr(settings):
    if settings.get("PR"):
        return settings["PR"]
    if not settings.get("SHA"):
        raise ValueError("Provide pr-number or commit-sha")
    result = subprocess.run(
        ["gh", "api", f"repos/{settings['GH_REPO']}/commits/{settings['SHA']}/pulls", "--paginate", "--slurp"],
        capture_output=True, text=True, check=True,
    )
    pulls = [pull for page in json.loads(result.stdout) for pull in page]
    merged = [pull for pull in pulls if pull.get("merged_at") and
              (not settings.get("BRANCH") or pull["base"]["ref"] == settings["BRANCH"])]
    return str(merged[0]["number"]) if merged else ""


def main():
    try:
        pr = find_pr(os.environ)
        if not pr:
            print("::warning::No merged pull request found for this commit; skipping PVF comment")
            return 0
        message = body(os.environ)
        with tempfile.TemporaryDirectory(prefix="pvf-comment-") as directory:
            path = Path(directory, "comment.md")
            path.write_text(message, encoding="utf-8")
            subprocess.run(["gh", "pr", "comment", pr, "--repo", os.environ["GH_REPO"],
                            "--body-file", str(path)], check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, ValueError, KeyError) as error:
        print(f"::error::PVF comment failed ({type(error).__name__}); check inputs and GitHub access")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
