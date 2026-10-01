from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


GENERATED_MARKER = "🤖 Generated with GitHub Actions"


def run(*command: str) -> None:
    subprocess.run(command, check=True)


def output(*command: str, check: bool = True) -> str:
    result = subprocess.run(command, check=check, stdout=subprocess.PIPE, text=True)
    return result.stdout.strip()


def has_staged_changes() -> bool:
    result = subprocess.run(("git", "diff", "--staged", "--quiet"), check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError("Could not inspect staged ruling changes")
    return result.returncode == 1


def create_fix_pr(target_ref: str, ruling_root: str, pr_number: str) -> tuple[str, str, str]:
    fix_branch = f"fix/update-ruling-for-{target_ref}"
    subject = f"PR #{pr_number}" if pr_number else target_ref
    title = f"Update ruling results for {subject}"
    body = f"Auto-generated ruling update for {subject}.\n\n{GENERATED_MARKER}"

    stash_created = bool(output("git", "status", "--porcelain", "--", ruling_root))
    if stash_created:
        run("git", "stash", "push", "--include-untracked", "-m", "ruling-sync-changes", "--", ruling_root)

    run("git", "fetch", "origin", "--", target_ref)
    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "github-actions[bot]@users.noreply.github.com")

    branch_exists = subprocess.run(
        ("git", "ls-remote", "--exit-code", "origin", "--", f"refs/heads/{fix_branch}"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    run("git", "switch", "-c", fix_branch, f"origin/{target_ref}")
    fix_base_sha = output("git", "rev-parse", "HEAD")

    if stash_created:
        try:
            run("git", "stash", "pop")
        except subprocess.CalledProcessError as error:
            subprocess.run(("git", "stash", "drop"), check=False)
            raise RuntimeError("Failed to apply stashed ruling changes") from error

    run("git", "add", ruling_root)
    fix_pr_url = ""
    committed = has_staged_changes()
    if committed:
        run("git", "commit", "-m", f"Update ruling results\n\n{GENERATED_MARKER}")
        if branch_exists:
            run("git", "push", "--force-with-lease", "origin", fix_branch)
        else:
            run("git", "push", "origin", fix_branch)

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

    fix_sha = output("git", "rev-parse", "HEAD")
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
