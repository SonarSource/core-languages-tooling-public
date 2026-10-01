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


def output(*command: str, check: bool = True) -> str:
    result = subprocess.run(command, check=check, stdout=subprocess.PIPE, text=True)
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


def create_fix_pr(target_ref: str, ruling_root: str, pr_number: str) -> tuple[str, str, str]:
    fix_branch = f"fix/update-ruling-for-{target_ref}"
    subject = f"PR #{pr_number}" if pr_number else target_ref
    title = f"Update ruling results for {subject}"
    body = f"Auto-generated ruling update for {subject}.\n\n{GENERATED_MARKER}"

    run("git", "fetch", "origin", "--", target_ref)
    remote_branch = subprocess.run(
        ("git", "ls-remote", "--exit-code", "origin", "--", f"refs/heads/{fix_branch}"),
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    if remote_branch.returncode not in (0, 2):
        raise RuntimeError("Could not inspect the remote fix branch")
    previous_sha = remote_branch.stdout.split()[0] if remote_branch.returncode == 0 else ""
    if remote_branch.returncode == 0 and not previous_sha:
        raise RuntimeError("Remote fix branch has no commit SHA")
    branch_exists = bool(previous_sha)

    with tempfile.TemporaryDirectory(prefix="ruling-fix-") as temporary_directory:
        worktree = Path(temporary_directory) / "checkout"
        run("git", "worktree", "add", "--detach", str(worktree), f"origin/{target_ref}")
        try:
            fix_base_sha = output("git", "-C", str(worktree), "rev-parse", "HEAD")
            transfer_ruling_changes(ruling_root, worktree)
            run("git", "-C", str(worktree), "add", "-A", "--", ruling_root)
            committed = has_staged_changes(worktree)
            if committed:
                run(
                    "git", "-C", str(worktree),
                    "-c", "user.name=github-actions[bot]",
                    "-c", "user.email=github-actions[bot]@users.noreply.github.com",
                    "commit", "-m", f"Update ruling results\n\n{GENERATED_MARKER}",
                )
                refspec = f"HEAD:refs/heads/{fix_branch}"
                if branch_exists:
                    run(
                        "git", "-C", str(worktree), "push",
                        f"--force-with-lease=refs/heads/{fix_branch}:{previous_sha}",
                        "origin", refspec,
                    )
                else:
                    run("git", "-C", str(worktree), "push", "origin", refspec)
            fix_sha = output("git", "-C", str(worktree), "rev-parse", "HEAD")
        finally:
            run("git", "worktree", "remove", "--force", str(worktree))

    fix_pr_url = ""
    if branch_exists:
        fix_pr_url = output(
            "gh", "pr", "list", "--head", fix_branch, "--base", target_ref,
            "--state", "open", "--json", "url", "--jq", ".[0].url // empty",
            check=False,
        )
    if (branch_exists or committed) and not fix_pr_url:
        fix_pr_url = output(
            "gh", "pr", "create", "--title", title, "--base", target_ref,
            "--head", fix_branch, "--body", body,
        )

    if pr_number and fix_pr_url:
        run(
            "gh", "pr", "comment", pr_number, "--body",
            f"⚖️ Ruling update ready for review: {fix_pr_url}",
        )
    return fix_pr_url, fix_base_sha, fix_sha


def main() -> int:
    try:
        fix_pr_url, fix_base_sha, fix_sha = create_fix_pr(
            os.environ["TARGET_REF"], os.environ["RULING_ROOT"], os.environ["PR_NUMBER"]
        )
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output_file:
            output_file.write(
                f"fix-pr-url={fix_pr_url}\nfix-base-sha={fix_base_sha}\nfix-sha={fix_sha}\n"
            )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
