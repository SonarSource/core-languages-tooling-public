from __future__ import annotations

import logging
from pathlib import PurePosixPath

from ruling_diff_core_lib.models_and_constants import (
    EXPECTED_RULING_ROOTS,
    IssueDiff,
    IssueLocation,
    OptionalRulingReport,
    RulingDiffIO,
    RuleDiff,
    RulingReport,
    SourceCache,
    Snippet,
)
from ruling_diff_core_lib.snippet_generation import build_snippets_for_rule
from ruling_diff_core_lib.report_formats import split_report_filename


def parse_ruling_path(path: str, ruling_root: str | None = None) -> tuple[str, str, str]:
    ruling_roots = (ruling_root,) if ruling_root is not None else EXPECTED_RULING_ROOTS
    matching_root = next(
        (root for root in ruling_roots if path.startswith(f"{root}/")), None
    )
    if matching_root is None:
        raise ValueError(f"Unexpected ruling path outside expected root: {path}")
    relative_path = path[len(matching_root) + 1 :]
    project, filename = parse_ruling_relative_path(relative_path)
    repository, rule_key = parse_rule_filename(filename)
    return project, repository, rule_key


def parse_ruling_relative_path(relative_path: str) -> tuple[str, str]:
    parts = PurePosixPath(relative_path).parts
    if len(parts) != 2:
        raise ValueError(
            f"Expected '<project>/<repo>-<rule>.<format>' path, got: {relative_path}"
        )
    return parts[0], parts[1]


def parse_rule_filename(filename: str) -> tuple[str, str]:
    basename, _ = split_report_filename(filename)
    if "-" not in basename:
        raise ValueError(f"Expected '<repo>-<ruleKey>.<format>', got: {filename}")
    repository, rule_key = basename.rsplit("-", 1)
    if not repository:
        raise ValueError(f"Missing repo in filename: {filename}")
    if not rule_key:
        raise ValueError(f"Missing rule key in filename: {filename}")
    return repository, rule_key


def strip_project_key(key: str) -> str:
    """
    Extract file path from ruling JSON key.

    Handles different formats:
    - Python: "airflow:airflow/cli/cli_parser.py" -> "airflow/cli/cli_parser.py"
    - Java Maven: "commons-beanutils:commons-beanutils:src/main/..." -> "src/main/..."
    - Java Maven: "org.eclipse.jetty:jetty-project:jetty-http/src/main/..." -> "jetty-http/src/main/..."

    Strategy:
    - If there are 3+ colon-separated parts (Java Maven format), return everything after the 2nd colon
    - Otherwise (Python format), return everything after the 1st colon
    """
    if ":" not in key:
        return key

    parts = key.split(":", 2)  # Split into at most 3 parts

    if len(parts) == 3:
        # Java Maven format: groupId:artifactId:path
        # Return just the path (3rd part)
        return parts[2]
    elif len(parts) == 2:
        # Python format: project:path
        # Return just the path (2nd part)
        return parts[1]
    else:
        # No colon, return as-is
        return key


def diff_ruling_jsons(
    old: OptionalRulingReport, new: OptionalRulingReport
) -> list[IssueDiff]:
    old_map = old or {}
    new_map = new or {}
    return [
        issue_diff
        for issue_diff in (
            diff_single_file_key(key, old_map, new_map)
            for key in sorted(set(old_map) | set(new_map))
        )
        if issue_diff is not None
    ]


def diff_single_file_key(
    key: str, old_map: RulingReport, new_map: RulingReport
) -> IssueDiff | None:
    old_locations = set(old_map.get(key, []))
    new_locations = set(new_map.get(key, []))
    added = sorted(new_locations - old_locations, key=IssueLocation.sort_key)
    removed = sorted(old_locations - new_locations, key=IssueLocation.sort_key)
    if not added and not removed:
        return None
    return IssueDiff(
        file_path=strip_project_key(key),
        added_lines=[location.start_line for location in added],
        removed_lines=[location.start_line for location in removed],
        added_locations=added,
        removed_locations=removed,
    )


def as_location(value: int | IssueLocation) -> IssueLocation:
    return IssueLocation(start_line=value) if isinstance(value, int) else value


def build_rule_diffs(
    changed_files: list[str],
    base_sha: str,
    head_sha: str,
    io: RulingDiffIO,
) -> list[RuleDiff]:
    source_cache: SourceCache = {}
    diffs = [
        build_rule_diff_for_file(
            path,
            base_sha,
            head_sha,
            source_cache,
            io,
        )
        for path in sorted(changed_files)
    ]
    return sorted(
        [rule_diff for rule_diff in diffs if rule_diff is not None],
        key=lambda diff: (diff.project, diff.repo, diff.rule_key),
    )


def build_rule_diff_for_file(
    path: str,
    base_sha: str,
    head_sha: str,
    source_cache: SourceCache,
    io: RulingDiffIO,
) -> RuleDiff | None:
    try:
        project, repository, rule_key = parse_ruling_path(path, io.ruling_root)
    except ValueError as exc:
        logging.warning("Skipping unrecognized ruling path %s: %s", path, exc)
        return None
    old_json: OptionalRulingReport = io.load_json_at_ref(path, base_sha)
    new_json: OptionalRulingReport = io.load_json_at_ref(path, head_sha)
    file_diffs: list[IssueDiff] = diff_ruling_jsons(old_json, new_json)
    if not file_diffs:
        return None
    snippets: list[Snippet] = build_snippets_for_rule(
        project,
        file_diffs,
        source_cache,
        base_sha,
        head_sha,
        io,
    )
    return RuleDiff(
        project=project,
        repo=repository,
        rule_key=rule_key,
        file_diffs=file_diffs,
        snippets=snippets,
        is_new_file=old_json is None,
        is_deleted_file=new_json is None,
    )
