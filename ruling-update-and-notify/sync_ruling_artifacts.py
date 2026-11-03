"""Copy downloaded ruling results into the selected expected directory.

Each ``actual_*`` artifact is downloaded separately. Artifact names are
processed in lexical order and the first artifact wins for duplicate paths.
This prevents concurrent extraction from corrupting overlapping SARIF files
and makes the selected platform deterministic.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


RESULT_SUFFIX = ".sarif"


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


def artifact_roots(artifact_directory: Path) -> list[tuple[str, Path]]:
    """Return isolated artifacts, or the flat layout used for one artifact."""
    isolated_artifacts = sorted(
        (entry for entry in artifact_directory.iterdir()
         if entry.is_dir() and entry.name.startswith("actual_")),
        key=lambda entry: entry.name,
    )
    if isolated_artifacts:
        return [(artifact.name, artifact) for artifact in isolated_artifacts]
    return [("downloaded artifact", artifact_directory)]


def has_symlink(root: Path, relative_path: Path) -> bool:
    """Whether the path or one of its parents below root is a symlink."""
    current = root
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def find_result_files(artifact_name: str, artifact_root: Path) -> list[tuple[str, Path, Path]]:
    """Return regular SARIF files and their paths relative to an artifact root."""
    if (artifact_root / "expected").exists():
        raise RuntimeError(f"Artifact {artifact_name!r} uses the obsolete expected/ wrapper")
    return [
        (artifact_name, source, source.relative_to(artifact_root))
        for source in sorted(artifact_root.rglob("*"), key=lambda path: path.as_posix())
        if source.suffix == RESULT_SUFFIX
        and not has_symlink(artifact_root, source.relative_to(artifact_root))
        and source.is_file()
    ]


def validate_download(artifact_directory: Path, download_outcome: str) -> list[tuple[str, Path, Path]]:
    if download_outcome != "success":
        print_diagnostics()
        raise RuntimeError(f"Failed to download artifacts (outcome: {download_outcome})")
    if not artifact_directory.is_dir():
        print_diagnostics()
        raise RuntimeError("No artifacts were downloaded (directory does not exist)")
    if not any(artifact_directory.iterdir()):
        raise RuntimeError("Artifact directory is empty; no 'actual_*' artifacts found")
    result_files = [
        result
        for artifact_name, artifact_root in artifact_roots(artifact_directory)
        for result in find_result_files(artifact_name, artifact_root)
    ]
    if not result_files:
        raise RuntimeError("Downloaded artifacts contain no regular SARIF result files")
    return result_files


def sync_artifacts(expected_root: Path, artifact_directory: Path, download_outcome: str) -> None:
    try:
        result_files = validate_download(artifact_directory, download_outcome)
        if not expected_root.is_dir():
            raise RuntimeError(f"Expected ruling directory does not exist: {expected_root}")
        selected_paths: set[Path] = set()
        for artifact_name, source, relative_path in result_files:
            if relative_path in selected_paths:
                print(f"Keeping {str(relative_path)!r} from an earlier artifact; skipping {artifact_name}")
                continue
            selected_paths.add(relative_path)
            destination = expected_root / relative_path
            if has_symlink(expected_root, relative_path):
                raise RuntimeError(f"Refusing to write through a symlink: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
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
