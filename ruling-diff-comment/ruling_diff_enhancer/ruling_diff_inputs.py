from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from html import unescape
from pathlib import Path
from typing import Iterator


RULE_HEADER = re.compile(
    r"^<summary><b>([^<]+)</b> \(<code>([^<]+)</code>\) on <b>([^<]+)</b>"
    r" - (\d+) issues removed, (\d+) issues added"
)
EXAMPLE_HEADER = re.compile(
    r"^\*\*(Added|Removed)\*\* `([^`]+)` \((?:line (\d+)|(file-level))"
    r"(?:, column \d+)?(?: to line \d+)?(?:, end column \d+)?\)$"
)
IGNORED_DIRECTORIES = {".git", ".venv", "venv", "node_modules", "target", "build"}


@dataclass
class RuleChange:
    rule_key: str
    repository: str
    removed_count: int = 0
    added_count: int = 0
    examples: list[dict] = field(default_factory=list)


def parse_comment(comment: str) -> list[RuleChange]:
    parser = _CommentParser(comment.splitlines())
    return parser.parse()


class _CommentParser:
    def __init__(self, lines: list[str]) -> None:
        self.lines = iter(lines)
        self.changes: dict[tuple[str, str], RuleChange] = {}
        self.current: RuleChange | None = None
        self.project = ""

    def parse(self) -> list[RuleChange]:
        for line in self.lines:
            if self._read_header(line):
                continue
            if line == "</details>":
                self.current = None
                continue
            if self._read_example(line):
                continue
            self._skip_code_block(line)
        if not self.changes:
            raise ValueError("No rule sections found; expected a ruling-diff-comment Markdown report")
        return list(self.changes.values())

    def _read_header(self, line: str) -> bool:
        header = RULE_HEADER.match(line)
        if header is None:
            return False
        self.current, self.project = _add_rule_header(self.changes, header)
        return True

    def _read_example(self, line: str) -> bool:
        example = EXAMPLE_HEADER.fullmatch(line)
        if example is None or self.current is None:
            return False
        change_kind, path, line_number, _ = example.groups()
        message, opening_fence = self._read_message_or_fence(path)
        fence = re.fullmatch(r"(`{3,})([^`]*)", opening_fence)
        if fence is None:
            raise ValueError(f"Missing code fence after example header: {line}")
        example_data = _example_data(
            self.current, self.project, change_kind, path, line_number, fence, self.lines,
        )
        if message is not None:
            example_data["message"] = message
        self.current.examples.append(example_data)
        return True

    def _read_message_or_fence(self, path: str) -> tuple[str | None, str]:
        opening_fence = next(self.lines, "")
        if not opening_fence.startswith("<pre>"):
            return None, opening_fence
        message_lines = [opening_fence]
        while not message_lines[-1].endswith("</pre>"):
            message_line = next(self.lines, None)
            if message_line is None:
                raise ValueError(f"Unclosed issue message for example: {path}")
            message_lines.append(message_line)
        return unescape("\n".join(message_lines)[5:-6]), next(self.lines, "")

    def _skip_code_block(self, line: str) -> None:
        if line.startswith("```"):
            fence = re.match(r"`{3,}", line).group()
            for snippet_line in self.lines:
                if snippet_line == fence:
                    break


def _example_data(
    current: RuleChange, project: str, change_kind: str, path: str, line_number: str | None,
    fence: re.Match[str], lines: Iterator[str],
) -> dict:
    body = []
    for snippet_line in lines:
        if snippet_line == fence.group(1):
            break
        body.append(snippet_line)
    else:
        raise ValueError(f"Unclosed code fence for example: {path}")
    return {
        "id": f"E{len(current.examples) + 1}", "project": project,
        "change_kind": change_kind.lower(), "file_path": path,
        "line_number": int(line_number) if line_number is not None else 0,
        "language": fence.group(2).strip(), "snippet": "\n".join(body),
    }


def _add_rule_header(
    changes: dict[tuple[str, str], RuleChange], header: re.Match[str],
) -> tuple[RuleChange, str]:
    rule_key, repository, project, removed, added = header.groups()
    rule_key, repository, project = unescape(rule_key), unescape(repository), unescape(project)
    current = changes.setdefault((repository, rule_key), RuleChange(rule_key, repository))
    current.removed_count += int(removed)
    current.added_count += int(added)
    return current, project


def find_configurations(repository: Path, explicit: Path | None = None) -> list[Path]:
    if explicit is not None:
        config = (repository / explicit).resolve()
        if not config.is_relative_to(repository) or not config.is_file():
            raise ValueError(f"Sonarpedia configuration must be a file inside {repository}: {config}")
        return [config]
    configurations = []
    for directory, children, files in os.walk(repository, followlinks=False):
        children[:] = sorted(child for child in children if child not in IGNORED_DIRECTORIES)
        if "sonarpedia.json" in files:
            configuration = Path(directory) / "sonarpedia.json"
            if not configuration.resolve().is_relative_to(repository):
                raise ValueError(f"Sonarpedia configuration escapes repository: {configuration}")
            configurations.append(configuration)
    if not configurations:
        raise ValueError(f"No sonarpedia.json found under {repository}")
    return configurations


def load_rule_metadata(repository: Path, configurations: list[Path], rule_key: str) -> dict:
    matches = []
    searched = []
    for config_path in configurations:
        metadata_root = _metadata_root(repository, config_path)
        searched.append(str(metadata_root))
        match = _metadata_match(repository, config_path, metadata_root, rule_key)
        if match is not None:
            matches.append(match)
    if not matches:
        raise ValueError(f"No HTML/JSON metadata pair for {rule_key}. Searched: {', '.join(searched)}")
    if len(matches) > 1:
        paths = ", ".join(match["sonarpedia_path"] for match in matches)
        raise ValueError(f"Ambiguous metadata for {rule_key}: {paths}. Select one with --sonarpedia")
    return matches[0]


def _metadata_root(repository: Path, config_path: Path) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    metadata_path = config.get("rules-metadata-path") if isinstance(config, dict) else None
    if not isinstance(metadata_path, str) or not metadata_path.strip():
        raise ValueError(f"Missing or invalid rules-metadata-path in {config_path}")
    metadata_root = (config_path.parent / metadata_path).resolve()
    if not metadata_root.is_relative_to(repository):
        raise ValueError(f"Metadata path escapes repository in {config_path}")
    return metadata_root


def _metadata_match(repository: Path, config_path: Path, metadata_root: Path, rule_key: str) -> dict | None:
    html_path = (metadata_root / f"{rule_key}.html").resolve()
    json_path = (metadata_root / f"{rule_key}.json").resolve()
    if not all(path.is_relative_to(repository) for path in (html_path, json_path)):
        raise ValueError(f"Rule metadata escapes repository for {rule_key}")
    if not html_path.is_file() or not json_path.is_file():
        return None
    metadata = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError(f"Rule metadata must be a JSON object: {json_path}")
    if metadata.get("sqKey", rule_key) != rule_key:
        raise ValueError(f"Rule key mismatch in {json_path}: expected {rule_key}")
    return {
        "sonarpedia_path": str(config_path.relative_to(repository)),
        "html_path": str(html_path.relative_to(repository)),
        "json_path": str(json_path.relative_to(repository)),
        "html": html_path.read_text(encoding="utf-8"), "json": metadata,
    }


def prepare_inputs(comment: str, repository: Path, explicit: Path | None = None) -> list[dict]:
    repository = repository.resolve()
    if not repository.is_dir():
        raise ValueError(f"Analyzer repository does not exist: {repository}")
    changes = parse_comment(comment)
    configurations = find_configurations(repository, explicit)
    return [_prepare_change(change, repository, configurations) for change in changes]


def _prepare_change(change: RuleChange, repository: Path, configurations: list[Path]) -> dict:
    _validate_example_paths(change, repository)
    return {**asdict(change), "metadata": load_rule_metadata(repository, configurations, change.rule_key)}


def _validate_example_paths(change: RuleChange, repository: Path) -> None:
    for example in change.examples:
        path = Path(example["file_path"])
        if path.is_absolute() or ".." in path.parts or not (repository / path).resolve().is_relative_to(repository):
            raise ValueError(
                f"Unsafe example path for {change.repository}:{change.rule_key}: {example['file_path']}"
            )
