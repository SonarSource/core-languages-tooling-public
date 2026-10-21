from __future__ import annotations

import os
import sys
from pathlib import Path


PUBLIC_ROOT = Path("its/ruling/src/test/resources")
PRIVATE_ROOT = Path("private/its/ruling/src/test/resources")


RULING_LAYOUTS = (
    (PUBLIC_ROOT, Path("its/sources")),
    (PRIVATE_ROOT, Path("private/its/sources")),
    (Path("private/its-enterprise/ruling/src/test/resources"), Path("private/its-enterprise/sources_ruling")),
)


def find_ruling_paths(repository_root: Path) -> tuple[Path, Path]:
    candidates = [
        (ruling_root, sources_root)
        for ruling_root, sources_root in RULING_LAYOUTS
        if (repository_root / ruling_root / "expected").is_dir()
    ]
    if len(candidates) > 1:
        found_roots = ", ".join(str(root / "expected") for root, _ in candidates)
        raise ValueError(f"Multiple expected ruling directories exist: {found_roots}")
    if candidates:
        return candidates[0]
    checked_roots = ", ".join(str(root / "expected") for root, _ in RULING_LAYOUTS)
    raise ValueError(f"No expected ruling directory found. Checked: {checked_roots}")


def main() -> int:
    try:
        ruling_root, sources_root = find_ruling_paths(Path.cwd())
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output_file:
            output_file.write(f"ruling-root={ruling_root}\nsources-root={sources_root}\n")
    except (OSError, ValueError) as error:
        print(f"::error::{error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
