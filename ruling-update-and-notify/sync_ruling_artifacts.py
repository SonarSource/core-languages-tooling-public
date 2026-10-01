"""Copy downloaded ruling artifacts into the repository's expectation tree.

The action merges ``actual_*`` artifacts into ``ruling-artifacts-temp``. This
script checks the download, copies its contents into the detected ruling
resources directory, and removes the temporary directory. A later step handles
committing the updated expectations and creating a fix PR.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


ARTIFACT_DIRECTORY = Path("ruling-artifacts-temp")


def print_diagnostics() -> None:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    print("Diagnostic information:")
    print(f"  Run ID: {run_id}")
    print(f"  Workflow run URL: https://github.com/{repository}/actions/runs/{run_id}")
    for name in ("GITHUB_REPOSITORY", "GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_SHA"):
        print(f"  {name}: {os.environ.get(name, '')}")
    print("Possible causes:")
    print("  1. No artifacts with pattern 'actual_*' were uploaded in previous jobs")
    print("  2. Artifacts expired or are not yet available")
    print("  3. Insufficient permissions to access artifacts")


def sync_artifacts(ruling_root: Path, artifact_directory: Path, download_outcome: str) -> None:
    if download_outcome != "success":
        print_diagnostics()
        raise RuntimeError(f"Failed to download artifacts (outcome: {download_outcome})")
    if not artifact_directory.is_dir():
        print_diagnostics()
        raise RuntimeError("No artifacts were downloaded (directory does not exist)")

    artifacts = list(artifact_directory.iterdir())
    if not artifacts:
        raise RuntimeError("Artifact directory is empty; no 'actual_*' artifacts found")

    print(f"Copying {len(artifacts)} artifact entries into {ruling_root}")
    try:
        for artifact in artifacts:
            destination = ruling_root / artifact.name
            if artifact.is_dir():
                shutil.copytree(artifact, destination, dirs_exist_ok=True, symlinks=True)
            else:
                shutil.copy2(artifact, destination, follow_symlinks=False)
    finally:
        shutil.rmtree(artifact_directory)
    print("Artifact sync complete")


def main() -> int:
    print("::group::Syncing ruling artifacts")
    try:
        sync_artifacts(
            Path(os.environ["RULING_ROOT"]),
            ARTIFACT_DIRECTORY,
            os.environ["DOWNLOAD_OUTCOME"],
        )
    except (OSError, RuntimeError) as error:
        print(f"::error::{error}", flush=True)
        return 1
    finally:
        print("::endgroup::")
    return 0


if __name__ == "__main__":
    sys.exit(main())
