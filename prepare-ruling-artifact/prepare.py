from __future__ import annotations

import os
import re
import sys
from pathlib import Path


RESULT_SUFFIX = ".sarif"
ACTUAL_ROOTS = (
    Path("its/ruling/target/actual"),
    Path("private/its/ruling/target/actual"),
    Path("private/its-enterprise/ruling/target/actual"),
    Path("its/ruling/build/actual"),
    Path("private/its/ruling/build/actual"),
    Path("private/its-enterprise/ruling/build/actual"),
)


def select_actual_root(actual_path: str | None = None) -> Path:
    if actual_path:
        root = Path(actual_path)
        if not root.is_absolute():
            root = Path(os.environ["GITHUB_WORKSPACE"]) / root
        if not root.is_dir():
            raise ValueError(f"Configured actual-path is not a directory: {root}")
        return root

    candidates = [root for root in ACTUAL_ROOTS if root.is_dir()]
    checked_roots = ", ".join(str(root) for root in ACTUAL_ROOTS)
    if len(candidates) > 1:
        found_roots = ", ".join(str(root) for root in candidates)
        raise ValueError(
            f"Multiple generated ruling directories found: {found_roots}. "
            f"Expected exactly one of: {checked_roots}"
        )
    if not candidates:
        raise ValueError(f"No generated ruling directory found. Checked: {checked_roots}")
    return candidates[0]


def has_result_files(root: Path) -> bool:
    return any(
        path.suffix == RESULT_SUFFIX and path.is_file() and not path.is_symlink()
        for path in root.rglob("*")
    )


def main() -> int:
    if not re.fullmatch(r"actual_[a-zA-Z0-9_.-]+", os.environ["ARTIFACT_NAME"]):
        raise ValueError(
            "artifact-name must begin with actual_ and contain only letters, numbers, _, ., or -"
        )

    actual_root = select_actual_root(os.environ.get("ACTUAL_PATH"))
    if not has_result_files(actual_root):
        raise ValueError(f"No generated ruling SARIF files found in {actual_root}")

    # The directory is uploaded as is: actual/project/report.sarif is stored
    # as project/report.sarif in the artifact.
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"path={actual_root}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
