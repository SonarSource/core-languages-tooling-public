from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


ACTUAL_ROOTS = (
    Path("its/ruling/target/actual"),
    Path("private/its/ruling/target/actual"),
    Path("its/ruling/build/actual"),
    Path("private/its/ruling/build/actual"),
    Path("build/actual"),
)


def select_actual_root() -> Path:
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


def main() -> int:
    if not re.fullmatch(r"actual_[a-zA-Z0-9_.-]+", os.environ["ARTIFACT_NAME"]):
        raise ValueError(
            "artifact-name must begin with actual_ and contain only letters, numbers, _, ., or -"
        )

    actual_root = select_actual_root()
    if not actual_root.is_dir() or not any(
        path.is_file() and not path.is_symlink()
        for path in actual_root.rglob("*.json")
    ):
        raise ValueError(f"No generated ruling JSON files found in {actual_root}")

    stage_root = Path(
        tempfile.mkdtemp(prefix="ruling-artifact.", dir=os.environ["RUNNER_TEMP"])
    )
    shutil.copytree(actual_root, stage_root / "expected", symlinks=True)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"path={stage_root}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
