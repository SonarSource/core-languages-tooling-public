"""Find a validated baseline, stopping at a published build from an earlier UTC day."""

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

VALIDATED_ARTIFACT = "pvf-validated"
CANDIDATE_ARTIFACT = "candidate-version"


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


def read_version(repository, run_id, artifact_name):
    """Download one artifact; malformed version files are not usable baselines."""
    with tempfile.TemporaryDirectory(prefix="pvf-baseline-") as directory:
        subprocess.run(
            ["gh", "run", "download", str(run_id), "--repo", repository,
             "--name", artifact_name, "--dir", directory],
            capture_output=True, text=True, check=True,
        )
        try:
            version = Path(directory, f"{artifact_name}.txt").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            version = ""
        if version and not any(char.isspace() for char in version):
            return version
        print(f"::warning::Ignoring missing or malformed version in run {run_id}")
        return ""


def is_published(repository, run, publication_job):
    jobs = pages(repository, f"actions/runs/{run['id']}/jobs", "jobs")
    return any(job["name"] == publication_job and job["conclusion"] == "success" for job in jobs)


def baseline_version(repository, run, today):
    """Prefer the validated marker; from an earlier UTC day on, accept the published candidate."""
    run_artifacts = pages(repository, f"actions/runs/{run['id']}/artifacts", "artifacts")
    artifacts = {artifact["name"] for artifact in run_artifacts if not artifact["expired"]}
    if VALIDATED_ARTIFACT in artifacts:
        version = read_version(repository, run["id"], VALIDATED_ARTIFACT)
        if version:
            return version

    # At the latest eligible build from yesterday (or earlier), stop waiting
    # for validation and use its published candidate. Never fall back today.
    created_at = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
    if created_at.astimezone(timezone.utc).date() < today and CANDIDATE_ARTIFACT in artifacts:
        version = read_version(repository, run["id"], CANDIDATE_ARTIFACT)
        if version:
            print("::notice::Using a published baseline from an earlier UTC day without a validated marker")
            return version
    return ""


def resolve(settings, today=None):
    """Inspect newest builds first, comparing commits rather than build versions."""
    today = today or datetime.now(timezone.utc).date()
    repository = settings["REPOSITORY"]
    runs = pages(repository, f"actions/workflows/{settings['BUILD_WORKFLOW']}/runs",
                 "workflow_runs", event="push", branch=settings["BRANCH"])

    for run in runs:
        if run["head_sha"] == settings["CURRENT_SHA"] \
                or not is_published(repository, run, settings["PUBLICATION_JOB"]):
            continue
        version = baseline_version(repository, run, today)
        if version:
            return version, run["head_sha"]
    return "", ""


def main():
    try:
        version, sha = resolve(os.environ)
    except (subprocess.CalledProcessError, ValueError, KeyError) as error:
        print(f"::error::PVF baseline lookup failed ({type(error).__name__}); check GitHub access and artifacts")
        return 1
    if not version:
        print("::warning::No eligible PVF baseline found; baseline outputs are empty")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"baseline-version={version}\nbaseline-sha={sha}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
