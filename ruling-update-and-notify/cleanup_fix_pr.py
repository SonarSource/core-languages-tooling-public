from __future__ import annotations

import os
import subprocess
import sys


def cleanup_fix_pr(target_ref: str) -> bool:
    fix_branch = f"fix/update-ruling-for-{target_ref}"
    state = subprocess.run(
        ("gh", "pr", "view", fix_branch, "--json", "state", "--jq", ".state"),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if state.returncode != 0 or state.stdout.strip() != "OPEN":
        return False

    print("Closing stale fix PR", flush=True)
    subprocess.run(
        (
            "gh", "pr", "close", fix_branch, "--comment",
            "No longer needed — the original PR is now up to date.",
        ),
        check=True,
    )
    subprocess.run(
        ("git", "push", "origin", "--delete", fix_branch),
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return True


def main() -> int:
    try:
        cleanup_fix_pr(os.environ["TARGET_REF"])
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"::error::{error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
