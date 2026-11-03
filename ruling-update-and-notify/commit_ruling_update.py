from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GENERATED_MARKER = "🤖 Generated with GitHub Actions"


def run(*command: str) -> None:
    subprocess.run(command, check=True)


def output(*command: str) -> str:
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True)
    return result.stdout.strip()


def has_staged_changes(worktree: Path) -> bool:
    result = subprocess.run(
        ("git", "-C", str(worktree), "diff", "--staged", "--quiet"), check=False
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("Could not inspect staged ruling changes")
    return result.returncode == 1


def transfer_ruling_changes(ruling_root: str, worktree: Path) -> None:
    patch = subprocess.run(
        ("git", "diff", "--binary", "HEAD", "--", ruling_root),
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    if patch:
        subprocess.run(
            ("git", "-C", str(worktree), "apply", "--3way", "--index"),
            input=patch,
            check=True,
        )

    untracked = output(
        "git", "ls-files", "--others", "--exclude-standard", "-z", "--", ruling_root
    )
    for relative_path in filter(None, untracked.split("\0")):
        source = Path(relative_path)
        destination = worktree / relative_path
        if destination.exists() or destination.is_symlink():
            raise RuntimeError(f"Ruling file already exists on target branch: {relative_path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)


def commit_ruling_update(target_ref: str, ruling_root: str, head_sha: str) -> tuple[str, str]:
    if not head_sha:
        raise RuntimeError("The PR head SHA is required for direct ruling updates")
    if output("git", "rev-parse", "HEAD") != head_sha:
        raise RuntimeError(
            "The checkout must match the PR head SHA; check out github.event.pull_request.head.sha, "
            "not the PR merge commit"
        )

    run("git", "check-ref-format", f"refs/heads/{target_ref}")
    run("git", "fetch", "origin", "--", f"refs/heads/{target_ref}")
    base_sha = output("git", "rev-parse", "FETCH_HEAD")
    if base_sha != head_sha:
        raise RuntimeError("The PR branch has changed since this run started; refusing a stale ruling update")

    with tempfile.TemporaryDirectory(prefix="ruling-update-") as temporary_directory:
        worktree = Path(temporary_directory) / "checkout"
        run("git", "worktree", "add", "--detach", str(worktree), base_sha)
        try:
            transfer_ruling_changes(ruling_root, worktree)
            run("git", "-C", str(worktree), "add", "-A", "--", ruling_root)
            if not has_staged_changes(worktree):
                return base_sha, ""
            run(
                "git", "-C", str(worktree),
                "-c", "user.name=github-actions[bot]",
                "-c", "user.email=github-actions[bot]@users.noreply.github.com",
                "commit", "-m", f"Update ruling results\n\n{GENERATED_MARKER}",
            )
            update_sha = output("git", "-C", str(worktree), "rev-parse", "HEAD")
            run("git", "-C", str(worktree), "push", "origin", f"HEAD:refs/heads/{target_ref}")
        finally:
            run("git", "worktree", "remove", "--force", str(worktree))
    return base_sha, update_sha


def main() -> int:
    try:
        base_sha, update_sha = commit_ruling_update(
            os.environ["TARGET_REF"], os.environ["RULING_ROOT"], os.environ["PR_HEAD_SHA"]
        )
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output_file:
            output_file.write(f"update-base-sha={base_sha}\nupdate-sha={update_sha}\n")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
