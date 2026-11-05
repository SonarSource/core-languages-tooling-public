from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path

from ruling_diff_core import RuleDiff, build_rule_diffs, format_comment
from ruling_diff_enhancer.enhance import review_comment
from ruling_diff_enhancer.rendering import format_reviewed_comment
from ruling_diff_enhancer.ruling_diff_models import has_api_key
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
        description="Generate a ruling diff comment and post it or preview it locally"
    )
    parser.add_argument("--pr-number")
    parser.add_argument("--repository")
    preview = parser.add_mutually_exclusive_group()
    preview.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the comment to stdout instead of posting it; no PR context required",
    )
    preview.add_argument(
        "--output-file",
        help="Write the comment to this file instead of posting it on the PR",
    )
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument(
        "--ruling-root",
        help="Override the standard and enterprise expected ruling directories"
    )
    parser.add_argument(
        "--sources-root",
        default=RULING_SOURCES_SUBMODULE,
        help="Path to sources directory"
    )
    args = parser.parse_args(argv)
    if not (args.dry_run or args.output_file):
        for argument in ("pr_number", "repository"):
            if not getattr(args, argument):
                parser.error(f"--{argument.replace('_', '-')} is required unless a preview mode is set")
    if args.repository and "/" not in args.repository:
        raise ValueError("--repository must be in owner/repo format")
    return args


def has_required_context(args: argparse.Namespace) -> bool:
    return bool(
        (args.dry_run or args.output_file or (args.pr_number or "").strip())
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
        return format_reviewed_comment(rule_diffs, reports)
    except Exception as error:
        logging.warning(
            "AI ruling diff review unavailable (%s); keeping the original diff comment.",
            type(error).__name__,
        )
        return comment


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
        logging.info("No changed ruling report files found. Nothing to do.")
        return None

    logging.info("Found %d changed ruling report files", len(changed_files))
    io = GitHubActionIO(ruling_root, sources_root)
    rule_diffs = build_rule_diffs(
        changed_files,
        base_sha,
        head_sha,
        io,
    )
    if not rule_diffs:
        logging.info("Changed files have no issue deltas. No comment will be posted.")
        return None

    comment = format_comment(rule_diffs)
    return add_enhancer_review(comment, rule_diffs)


def resolve_output_file(output_file: str) -> Path:
    target = Path(output_file).resolve()
    # /tmp supports the documented CLI path when TMPDIR points elsewhere.
    # Resolve the target and require containment before writing.
    allowed_roots = (
        Path.cwd().resolve(),
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp").resolve(),  # NOSONAR
    )
    if not any(target.is_relative_to(root) for root in allowed_roots):
        raise ValueError("--output-file must be inside the current directory, system temporary directory, or /tmp")
    return target


def write_output_file(target: Path, comment: str | None) -> None:
    target.write_text(comment or "", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    configure_logging()
    args = parse_args(argv)
    output_file = resolve_output_file(args.output_file) if args.output_file else None
    if not has_required_context(args):
        logging.info("Missing pr/base/head arguments. Skipping ruling diff comment.")
        return

    comment = generate_comment(
        args.base_sha, args.head_sha, args.ruling_root, args.sources_root
    )
    if args.dry_run:
        if comment:
            print(comment)
    elif output_file is not None:
        write_output_file(output_file, comment)
    elif comment:
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
