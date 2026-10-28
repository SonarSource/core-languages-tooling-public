"""Copy downloaded ruling results into the selected expected directory.

The action merges ``actual_*`` artifacts into ``ARTIFACT_DIRECTORY``. Each
artifact contains the generated results relative to the actual directory, so
``project/report.json`` updates ``<expected-root>/project/report.json``. This
script validates the download, copies only regular JSON and SARIF files, and
removes the temporary directory. Expectations for projects absent from the
artifacts are kept. A later step commits the updated expectations and creates
a fix PR.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


RESULT_SUFFIXES = (".json", ".sarif")
LEGACY_WRAPPER = "expected"


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


def find_result_files(artifact_directory: Path) -> list[Path]:
    """Return regular JSON and SARIF files, relative to the artifact directory."""
    return sorted(
        relative_path
        for relative_path in (
            path.relative_to(artifact_directory) for path in artifact_directory.rglob("*")
        )
        if relative_path.suffix in RESULT_SUFFIXES
        and not has_symlink(artifact_directory, relative_path)
        and (artifact_directory / relative_path).is_file()
    )


def has_symlink(root: Path, relative_path: Path) -> bool:
    """Whether the path or one of its parents below root is a symlink."""
    current = root
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def validate_download(artifact_directory: Path, download_outcome: str) -> list[Path]:
    if download_outcome != "success":
        print_diagnostics()
        raise RuntimeError(f"Failed to download artifacts (outcome: {download_outcome})")
    if not artifact_directory.is_dir():
        print_diagnostics()
        raise RuntimeError("No artifacts were downloaded (directory does not exist)")
    if not any(artifact_directory.iterdir()):
        raise RuntimeError("Artifact directory is empty; no 'actual_*' artifacts found")
    if (artifact_directory / LEGACY_WRAPPER).is_dir():
        raise RuntimeError(
            f"Artifacts use the obsolete '{LEGACY_WRAPPER}/' wrapper; upload the generated "
            "actual directory with the matching prepare-ruling-artifact version"
        )
    result_files = find_result_files(artifact_directory)
    if not result_files:
        raise RuntimeError("Downloaded artifacts contain no regular JSON or SARIF result files")
    return result_files


def sync_artifacts(expected_root: Path, artifact_directory: Path, download_outcome: str) -> None:
    try:
        result_files = validate_download(artifact_directory, download_outcome)
        if not expected_root.is_dir():
            raise RuntimeError(f"Expected ruling directory does not exist: {expected_root}")
        print(f"Copying {len(result_files)} result files into {expected_root}")
        for relative_path in result_files:
            destination = expected_root / relative_path
            if has_symlink(expected_root, relative_path):
                raise RuntimeError(f"Refusing to write through a symlink: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(artifact_directory / relative_path, destination)
    finally:
        if artifact_directory.is_dir():
            shutil.rmtree(artifact_directory)
    print("Artifact sync complete")


def main() -> int:
    print("::group::Syncing ruling artifacts")
    try:
        sync_artifacts(
            Path(os.environ["EXPECTED_ROOT"]),
            Path(os.environ["ARTIFACT_DIRECTORY"]),
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
