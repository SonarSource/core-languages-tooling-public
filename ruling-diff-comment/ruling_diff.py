from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from ruling_diff_core import build_rule_diffs, format_comment
from ruling_diff_io import (
    GitHubActionIO,
    RULING_SOURCES_SUBMODULE,
    get_changed_ruling_files,
    post_or_update_comment,
)


def configure_logging() -> None:
    level = logging.DEBUG if os.environ.get("RUNNER_DEBUG") else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and post ruling diff comment"
    )
    parser.add_argument("--pr-number", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument(
        "--ruling-root",
        help="Override the standard and enterprise expected ruling directories"
    )
    parser.add_argument(
        "--sources-root",
        default="private/its-enterprise/sources_ruling",
        help="Path to sources directory"
    )
    parser.add_argument(
        "--output-file",
        help="Write the comment to this file instead of posting it on the PR"
    )
    args = parser.parse_args(argv)
    if not args.output_file and "/" not in args.repository:
        raise ValueError("--repository must be in owner/repo format")
    return args


def has_required_context(args: argparse.Namespace) -> bool:
    return bool(
        (args.output_file or args.pr_number.strip())
        and args.base_sha.strip()
        and args.head_sha.strip()
    )


def generate_comment(
    base_sha: str,
    head_sha: str,
    ruling_root: str | None = None,
    sources_root: str = RULING_SOURCES_SUBMODULE,
) -> str | None:
    changed_files = get_changed_ruling_files(
        base_sha, head_sha, ruling_root
    )
    if not changed_files:
        logging.info("No changed ruling json files found. Nothing to do.")
        return None

    logging.info("Found %d changed ruling json files", len(changed_files))
    io = GitHubActionIO(ruling_root, sources_root)
    rule_diffs = build_rule_diffs(
        changed_files,
        base_sha,
        head_sha,
        io,
    )
    if not rule_diffs:
        logging.info("Changed files have no issue deltas. No comment will be generated.")
        return None
    return format_comment(rule_diffs)


def main(argv: list[str] | None = None) -> None:
    configure_logging()
    args = parse_args(argv)
    if not has_required_context(args):
        logging.info("Missing pr/base/head arguments. Skipping ruling diff comment.")
        return

    comment = generate_comment(
        args.base_sha, args.head_sha, args.ruling_root, args.sources_root
    )
    if args.output_file:
        Path(args.output_file).write_text(comment or "", encoding="utf-8")
    elif comment:
        post_or_update_comment(args.pr_number, args.repository, comment)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Failed to generate ruling diff comment")
        sys.exit(1)
