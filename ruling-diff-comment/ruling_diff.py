from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from ruling_diff_core import RuleDiff, build_rule_diffs, format_comment
from ruling_diff_enhancer.enhance import render_markdown, review_comment
from ruling_diff_enhancer.ruling_diff_models import has_api_key
from ruling_diff_io import (
    GitHubActionIO,
    get_changed_ruling_files,
    post_or_update_comment,
)


def configure_logging() -> None:
    level = logging.DEBUG if os.environ.get("RUNNER_DEBUG") else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a ruling diff comment and post it or preview it locally"
    )
    parser.add_argument("--pr-number")
    parser.add_argument("--repository")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the comment to stdout instead of posting it; no PR context required",
    )
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
    args = parser.parse_args()
    if not args.dry_run:
        for argument in ("pr_number", "repository"):
            if getattr(args, argument) is None:
                parser.error(f"--{argument.replace('_', '-')} is required unless --dry-run is set")
    if args.repository is not None and "/" not in args.repository:
        raise ValueError("--repository must be in owner/repo format")
    return args


def has_required_context(args: argparse.Namespace) -> bool:
    return bool(
        (args.dry_run or args.pr_number.strip())
        and args.base_sha.strip()
        and args.head_sha.strip()
    )


def add_enhancer_review(comment: str, rule_diffs: list[RuleDiff]) -> str:
    model = os.environ.get("DSPY_MODEL", "").strip()
    if not model:
        return comment
    provider = os.environ.get("DSPY_PROVIDER", "auto")
    api_base = os.environ.get("DSPY_API_BASE")
    try:
        if not has_api_key(model, provider, api_base):
            return comment
        reports = review_comment(
            comment, Path.cwd(), model=model, provider=provider, api_base=api_base,
        )
        return format_comment(rule_diffs, review=render_markdown(reports))
    except Exception as error:
        logging.warning(
            "AI ruling diff review unavailable (%s); keeping the original diff comment.",
            type(error).__name__,
        )
        return comment


def main() -> None:
    configure_logging()
    args = parse_args()
    if not has_required_context(args):
        logging.info("Missing pr/base/head arguments. Skipping ruling diff comment.")
        return

    changed_files = get_changed_ruling_files(
        args.base_sha, args.head_sha, args.ruling_root
    )
    if not changed_files:
        logging.info("No changed ruling report files found. Nothing to do.")
        return

    logging.info("Found %d changed ruling report files", len(changed_files))
    io = GitHubActionIO(args.ruling_root, args.sources_root)
    rule_diffs = build_rule_diffs(
        changed_files,
        args.base_sha,
        args.head_sha,
        io,
    )
    if not rule_diffs:
        logging.info("Changed files have no issue deltas. No comment will be posted.")
        return

    comment = format_comment(rule_diffs)
    comment = add_enhancer_review(comment, rule_diffs)
    if args.dry_run:
        print(comment)
    else:
        post_or_update_comment(args.pr_number, args.repository, comment)


def entrypoint() -> int:
    try:
        main()
    except Exception:
        logging.exception("Failed to generate ruling diff comment")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(entrypoint())
