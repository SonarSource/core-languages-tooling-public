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


def select_actual_root(override: str) -> Path:
    if override:
        return Path(override)
    candidates = [root for root in ACTUAL_ROOTS if root.is_dir()]
    if len(candidates) > 1:
        raise ValueError("Multiple generated ruling directories found; set actual-root")
    if not candidates:
        raise ValueError("No generated ruling directory found; set actual-root")
    return candidates[0]


def main() -> int:
    if not re.fullmatch(r"actual_[a-zA-Z0-9_.-]+", os.environ["ARTIFACT_NAME"]):
        raise ValueError(
            "artifact-name must begin with actual_ and contain only letters, numbers, _, ., or -"
        )

    actual_root = select_actual_root(os.environ["ACTUAL_ROOT"])
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
