"""Resolve a deployed PVF baseline using GitHub Actions artifacts."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlencode


def api(repository, path):
    result = subprocess.run(
        ["gh", "api", f"repos/{repository}/{path}"], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def pages(repository, path, key, **query):
    page = 1
    while True:
        data = api(repository, f"{path}?{urlencode({**query, 'per_page': 100, 'page': page})}")
        items = data[key]
        yield from items
        if len(items) < 100:
            return
        page += 1


def warning(message):
    print("::warning::" + message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A"))


def resolve(settings):
    repository = settings["REPOSITORY"]
    branch = settings["BRANCH"]
    workflow = settings["BUILD_WORKFLOW"]
    excluded_sha = settings.get("CURRENT_SHA", "")
    excluded_run = settings.get("CURRENT_RUN_ID", "")
    checked = set()

    def pick(candidates, artifact_name):
        for candidate in candidates:
            run_id = str(candidate["id"])
            sha = candidate["head_sha"]
            if sha == excluded_sha or run_id == excluded_run or (run_id, artifact_name) in checked:
                continue
            checked.add((run_id, artifact_name))
            if candidate.get("head_branch") != branch or candidate.get("event") != "push":
                continue
            jobs = pages(repository, f"actions/runs/{run_id}/jobs", "jobs")
            if not any(job["name"] == settings["PUBLICATION_JOB"] and job["conclusion"] == "success" for job in jobs):
                continue
            artifacts = pages(repository, f"actions/runs/{run_id}/artifacts", "artifacts")
            if not any(a["name"] == artifact_name and not a["expired"] for a in artifacts):
                continue
            with tempfile.TemporaryDirectory(prefix="pvf-baseline-") as directory:
                subprocess.run(
                    ["gh", "run", "download", run_id, "--repo", repository,
                     "--name", artifact_name, "--dir", directory],
                    capture_output=True, text=True, check=True,
                )
                path = Path(directory, f"{artifact_name}.txt")
                try:
                    version = path.read_text(encoding="utf-8").strip()
                except (OSError, UnicodeError):
                    warning(f"Ignoring malformed {artifact_name} artifact from run {run_id}")
                    continue
                if not version or any(char.isspace() for char in version):
                    warning(f"Ignoring empty or malformed version in run {run_id}")
                    continue
                return version, sha
        return None

    def validated_runs():
        seen = set()
        workflow_id = api(repository, f"actions/workflows/{workflow}")["id"]
        for artifact in pages(repository, "actions/artifacts", "artifacts", name=settings["VALIDATED_ARTIFACT"]):
            run = artifact.get("workflow_run") or {}
            if artifact["expired"] or run.get("head_branch") != branch or run["id"] in seen:
                continue
            seen.add(run["id"])
            if str(run["id"]) == excluded_run or run.get("head_sha") == excluded_sha:
                continue
            details = api(repository, f"actions/runs/{run['id']}")
            if details["workflow_id"] == workflow_id:
                yield details

    result = pick(validated_runs(), settings["VALIDATED_ARTIFACT"])
    if result:
        return result
    previous = settings.get("PREVIOUS_SHA", "")
    if previous and set(previous) != {"0"}:
        result = pick(pages(repository, f"actions/workflows/{workflow}/runs", "workflow_runs",
                            head_sha=previous, event="push", branch=branch), settings["CANDIDATE_ARTIFACT"])
        if result:
            return result
    result = pick(pages(repository, f"actions/workflows/{workflow}/runs", "workflow_runs",
                        event="push", branch=branch), settings["CANDIDATE_ARTIFACT"])
    return result or ("", "")


def main():
    try:
        version, sha = resolve(os.environ)
    except (subprocess.CalledProcessError, ValueError, KeyError) as error:
        # Do not echo subprocess stderr: it may include credentials or server content.
        print(f"::error::PVF baseline lookup failed ({type(error).__name__}); check GitHub access and artifact availability")
        return 1
    if not version:
        warning("No deployed PVF baseline could be resolved; baseline outputs are empty")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"baseline-version={version}\nbaseline-sha={sha}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
