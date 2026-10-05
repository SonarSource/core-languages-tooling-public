from __future__ import annotations

import os
import sys
from pathlib import Path


PUBLIC_ROOT = Path("its/ruling/src/test/resources")
PRIVATE_ROOT = Path("private/its/ruling/src/test/resources")


def find_ruling_paths(repository_root: Path) -> tuple[Path, Path]:
    public_expected = PUBLIC_ROOT / "expected"
    private_expected = PRIVATE_ROOT / "expected"
    has_public = (repository_root / public_expected).is_dir()
    has_private = (repository_root / private_expected).is_dir()

    if has_public and has_private:
        raise ValueError(
            f"Both expected ruling directories exist: {public_expected} and {private_expected}"
        )
    if has_public:
        return PUBLIC_ROOT, Path("its/sources")
    if has_private:
        return PRIVATE_ROOT, Path("private/its/sources")
    raise ValueError(
        f"No expected ruling directory found. Checked: {public_expected}, {private_expected}"
    )


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
