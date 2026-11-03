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


def downloaded_artifacts(artifact_directory: Path, download_outcome: str) -> list[Path]:
    if download_outcome != "success":
        print_diagnostics()
        raise RuntimeError(f"Failed to download artifacts (outcome: {download_outcome})")
    if not artifact_directory.is_dir():
        print_diagnostics()
        raise RuntimeError("No artifacts were downloaded (directory does not exist)")
    artifacts = list(artifact_directory.iterdir())
    if not artifacts:
        raise RuntimeError("Artifact directory is empty; no 'actual_*' artifacts found")
    return artifacts


def isolated_artifacts(artifacts: list[Path]) -> list[Path]:
    return sorted(
        (artifact for artifact in artifacts if artifact.is_dir() and artifact.name.startswith("actual_")),
        key=lambda artifact: artifact.name,
    )


def copy_entries(source_root: Path, ruling_root: Path) -> None:
    for source in source_root.iterdir():
        destination = ruling_root / source.name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)
        else:
            shutil.copy2(source, destination, follow_symlinks=False)


def sync_isolated_artifacts(ruling_root: Path, artifacts: list[Path]) -> None:
    destination_root = ruling_root / "expected"
    destination_root.mkdir(parents=True, exist_ok=True)
    print(f"Copying {len(artifacts)} isolated artifacts into {destination_root}")
    for artifact in artifacts:
        source_root = artifact / "expected" if (artifact / "expected").is_dir() else artifact
        copy_entries(source_root, destination_root)


def sync_downloaded_artifact(ruling_root: Path, artifacts: list[Path], artifact_directory: Path) -> None:
    # prepare-ruling-artifact wraps results in expected/. Older producers upload
    # target/actual contents directly, so those need the expected/ destination.
    if not (artifact_directory / "expected").is_dir():
        ruling_root = ruling_root / "expected"
    ruling_root.mkdir(parents=True, exist_ok=True)
    print(f"Copying {len(artifacts)} artifact entries into {ruling_root}")
    copy_entries(artifact_directory, ruling_root)


def sync_artifacts(ruling_root: Path, artifact_directory: Path, download_outcome: str) -> None:
    artifacts = downloaded_artifacts(artifact_directory, download_outcome)
    isolated = isolated_artifacts(artifacts)
    try:
        if isolated:
            sync_isolated_artifacts(ruling_root, isolated)
        else:
            sync_downloaded_artifact(ruling_root, artifacts, artifact_directory)
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
