from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from ruling_diff_core_lib.sarif import parse_sarif_report
from ruling_diff_core_lib.models_and_constants import (
    COMMENT_MARKER,
    EXPECTED_RULING_ROOTS,
    PROJECT_SOURCE_OVERRIDES,
    OptionalSarifReport,
)

RULING_SOURCES_SUBMODULE = "private/its-enterprise/sources_ruling"
SOURCES_INTERNAL_RULING_ROOT = "private/its-enterprise/sources_internal_ruling"
SOURCES_INTERNAL_NAMESPACE_RULING_ROOT = (
    "private/its-enterprise/sources_internal_namespace_ruling"
)


class CommandError(RuntimeError):
    pass


class GitHubActionIO:
    def __init__(
        self,
        ruling_root: str | None = None,
        sources_root: str = RULING_SOURCES_SUBMODULE,
    ):
        self.ruling_root = ruling_root
        self.sources_root = sources_root

    def load_sarif_at_ref(self, path: str, ref: str) -> OptionalSarifReport:
        return load_sarif_at_ref(path, ref)

    def load_text_at_ref(self, path: str, ref: str) -> str | None:
        return load_text_at_ref(path, ref, self.sources_root)

    def resolve_source_path(self, project: str, file_path: str) -> str:
        if project == "project":
            return self._resolve_project_source_path(file_path)
        source_root = PROJECT_SOURCE_OVERRIDES.get(
            project, f"{self.sources_root}/{project}"
        )
        return f"{source_root}/{file_path.lstrip('/')}"

    def _resolve_project_source_path(self, file_path: str) -> str:
        clean_path = file_path.lstrip("/")
        primary_candidate = f"{self.sources_root}/{clean_path}"
        candidates = [primary_candidate]
        candidates.extend(
            self._with_direct_children_prefixes(self.sources_root, clean_path)
        )
        candidates.append(f"{SOURCES_INTERNAL_RULING_ROOT}/{clean_path}")
        candidates.append(f"{SOURCES_INTERNAL_NAMESPACE_RULING_ROOT}/{clean_path}")
        candidates.extend(
            self._with_direct_children_prefixes(
                SOURCES_INTERNAL_NAMESPACE_RULING_ROOT, clean_path
            )
        )
        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate
        return primary_candidate

    def _with_direct_children_prefixes(self, root: str, file_path: str) -> list[str]:
        root_path = Path(root)
        if not root_path.is_dir():
            return []
        return [
            f"{root}/{child.name}/{file_path}"
            for child in sorted(root_path.iterdir(), key=lambda path: path.name)
            if child.is_dir() and not child.name.startswith(".")
        ]


def run_command(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise CommandError(
            format_command_failure(
                command, result.stdout, result.stderr, result.returncode
            )
        )
    return result.stdout


def format_command_failure(
    command: list[str], stdout: str, stderr: str, returncode: int
) -> str:
    return (
        f"Command failed with exit code {returncode}: {' '.join(command)}\n"
        f"stdout: {stdout}\n"
        f"stderr: {stderr}"
    )


def run_gh_json(command: list[str]) -> dict | list:
    output = run_command(["gh", *command])
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise CommandError(f"Could not parse JSON from gh output: {exc}") from exc


def run_gh_paginated_items(endpoint: str) -> list[dict]:
    output = run_command(["gh", "api", "--paginate", endpoint])
    docs = parse_json_documents(output)
    items: list[dict] = []
    for doc in docs:
        if not isinstance(doc, list):
            raise CommandError("Unexpected response type while listing paginated items")
        for item in doc:
            if isinstance(item, dict):
                items.append(item)
    return items


def parse_json_documents(content: str) -> list[object]:
    decoder = json.JSONDecoder()
    index = 0
    documents: list[object] = []
    while index < len(content):
        while index < len(content) and content[index].isspace():
            index += 1
        if index >= len(content):
            break
        document, next_index = decoder.raw_decode(content, index)
        documents.append(document)
        index = next_index
    return documents


def get_changed_ruling_files(
    base_sha: str, head_sha: str, ruling_root: str | None = None
) -> list[str]:
    ruling_roots = (ruling_root,) if ruling_root is not None else EXPECTED_RULING_ROOTS
    output = run_command(
        [
            "git",
            "diff",
            "--name-only",
            f"{base_sha}...{head_sha}",
            "--",
            *(f"{root}/" for root in ruling_roots),
        ]
    )
    changed = [
        path
        for path in (line.strip() for line in output.splitlines())
        if is_ruling_report(path, ruling_root)
    ]
    return sorted(set(changed))


def is_ruling_report(path: str, ruling_root: str | None = None) -> bool:
    ruling_roots = (ruling_root,) if ruling_root is not None else EXPECTED_RULING_ROOTS
    return path.endswith(".sarif") and any(
        path.startswith(f"{root}/") for root in ruling_roots
    )


def _is_missing_at_ref(stderr: str) -> bool:
    return any(
        marker in stderr
        for marker in ("exists on disk, but not in", "does not exist in")
    )


def load_sarif_at_ref(path: str, ref: str) -> OptionalSarifReport:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"], capture_output=True, text=True
    )
    if result.returncode != 0:
        if _is_missing_at_ref(result.stderr):
            return None
        raise CommandError(
            f"Failed to read file at ref: git show {ref}:{path}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return parse_sarif_report(result.stdout, path, ref)


def load_text_at_ref(path: str, ref: str, sources_root: str = RULING_SOURCES_SUBMODULE) -> str | None:
    if is_ruling_source_path(path, sources_root):
        return load_submodule_text_at_ref(path, ref, sources_root)

    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"], capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout
    if _is_missing_at_ref(result.stderr):
        logging.warning("Source file '%s' not found at %s", path, ref)
        return None
    raise CommandError(
        f"Failed to read source file at ref: git show {ref}:{path}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def is_ruling_source_path(path: str, sources_root: str = RULING_SOURCES_SUBMODULE) -> bool:
    return path.startswith(f"{sources_root}/")


def load_submodule_text_at_ref(path: str, ref: str, sources_root: str = RULING_SOURCES_SUBMODULE) -> str | None:
    submodule_commit = get_submodule_commit_for_ref(ref, sources_root)
    if submodule_commit is None:
        logging.warning("Source file '%s' not found at %s", path, ref)
        return None

    submodule_relative_path = path[len(f"{sources_root}/") :]
    content = read_submodule_file_at_commit(submodule_commit, submodule_relative_path, sources_root)
    if content is not None:
        return content

    fetch_submodule_commit(submodule_commit, sources_root)
    content = read_submodule_file_at_commit(submodule_commit, submodule_relative_path, sources_root)
    if content is not None:
        return content

    logging.warning(
        "Source file '%s' not found in submodule commit %s for %s",
        path,
        submodule_commit,
        ref,
    )
    return None


def get_submodule_commit_for_ref(ref: str, sources_root: str = RULING_SOURCES_SUBMODULE) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", f"{ref}:{sources_root}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logging.warning(
            "Could not resolve ruling sources submodule commit for %s: %s",
            ref,
            result.stderr.strip(),
        )
        return None
    return result.stdout.strip()


def read_submodule_file_at_commit(commit: str, relative_path: str, sources_root: str = RULING_SOURCES_SUBMODULE) -> str | None:
    result = subprocess.run(
        ["git", "-C", sources_root, "show", f"{commit}:{relative_path}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout
    return None


def fetch_submodule_commit(commit: str, sources_root: str = RULING_SOURCES_SUBMODULE) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            sources_root,
            "fetch",
            "--depth",
            "1",
            "origin",
            commit,
        ],
        capture_output=True,
        text=True,
    )


def get_existing_comment_id(pr_number: str, repository: str) -> str | None:
    comments = run_gh_paginated_items(
        f"repos/{repository}/issues/{pr_number}/comments?per_page=100"
    )
    for comment in comments:
        if COMMENT_MARKER in comment.get("body", ""):
            return str(comment["id"])
    return None


def post_or_update_comment(pr_number: str, repository: str, body: str) -> None:
    comment_id = get_existing_comment_id(pr_number, repository)
    if comment_id is None:
        logging.info("Posting new ruling diff comment on PR #%s", pr_number)
        run_command(
            ["gh", "pr", "comment", pr_number, "--repo", repository, "--body", body]
        )
        return
    logging.info(
        "Updating existing ruling diff comment %s on PR #%s", comment_id, pr_number
    )
    run_command(
        [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"repos/{repository}/issues/comments/{comment_id}",
            "-f",
            f"body={body}",
        ]
    )
