from __future__ import annotations

import os
import sys
from pathlib import Path


PUBLIC_EXPECTED_ROOT = Path("its/ruling/src/test/resources/expected")
PRIVATE_EXPECTED_ROOT = Path("private/its/ruling/src/test/resources/expected")
ENTERPRISE_EXPECTED_ROOT = Path("private/its-enterprise/ruling/src/test/resources/expected")
PUBLIC_SOURCES_ROOT = Path("its/sources")
PRIVATE_SOURCES_ROOT = Path("private/its/sources")
ENTERPRISE_SOURCES_ROOT = Path("private/its-enterprise/sources_ruling")


RULING_LAYOUTS = (
    (PUBLIC_EXPECTED_ROOT, PUBLIC_SOURCES_ROOT),
    (PRIVATE_EXPECTED_ROOT, PRIVATE_SOURCES_ROOT),
    (ENTERPRISE_EXPECTED_ROOT, ENTERPRISE_SOURCES_ROOT),
)


def find_ruling_paths(repository_root: Path) -> tuple[Path, Path]:
    """Return the expected directory and the matching test project sources."""
    candidates = [
        (expected_root, sources_root)
        for expected_root, sources_root in RULING_LAYOUTS
        if (repository_root / expected_root).is_dir()
    ]
    if len(candidates) > 1:
        found_roots = ", ".join(str(root) for root, _ in candidates)
        raise ValueError(f"Multiple expected ruling directories exist: {found_roots}")
    if candidates:
        return candidates[0]
    checked_roots = ", ".join(str(root) for root, _ in RULING_LAYOUTS)
    raise ValueError(f"No expected ruling directory found. Checked: {checked_roots}")


def main() -> int:
    try:
        expected_root, sources_root = find_ruling_paths(Path.cwd())
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output_file:
            output_file.write(f"expected-root={expected_root}\nsources-root={sources_root}\n")
    except (OSError, ValueError) as error:
        print(f"::error::{error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
