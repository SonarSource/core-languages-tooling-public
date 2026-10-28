from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from html import unescape
from pathlib import Path


RULE_HEADER = re.compile(
    r"^<summary><b>(S\d+)</b> \(<code>([^<]+)</code>\) on <b>([^<]+)</b>"
    r" - (\d+) issues removed, (\d+) issues added"
)
EXAMPLE_HEADER = re.compile(
    r"^\*\*(Added|Removed)\*\* `([^`]+)` \((?:line (\d+)|(file-level))\)$"
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
    changes: dict[tuple[str, str], RuleChange] = {}
    current: RuleChange | None = None
    project = ""
    lines = iter(comment.splitlines())
    for line in lines:
        header = RULE_HEADER.match(line)
        if header:
            rule_key, repository, project, removed, added = header.groups()
            repository, project = unescape(repository), unescape(project)
            current = changes.setdefault(
                (repository, rule_key), RuleChange(rule_key, repository)
            )
            current.removed_count += int(removed)
            current.added_count += int(added)
            continue
        if line == "</details>":
            current = None
        example = EXAMPLE_HEADER.fullmatch(line)
        if example and current is not None:
            change_kind, path, line_number, _ = example.groups()
            opening_fence = next(lines, "")
            fence = re.fullmatch(r"(`{3,})([^`]*)", opening_fence)
            if fence is None:
                raise ValueError(f"Missing code fence after example header: {line}")
            body = []
            for snippet_line in lines:
                if snippet_line == fence.group(1):
                    break
                body.append(snippet_line)
            else:
                raise ValueError(f"Unclosed code fence for example: {path}")
            current.examples.append({
                "id": f"E{len(current.examples) + 1}",
                "project": project,
                "change_kind": change_kind.lower(),
                "file_path": path,
                "line_number": int(line_number) if line_number is not None else 0,
                "language": fence.group(2).strip(),
                "snippet": "\n".join(body),
            })
        elif line.startswith("```"):
            fence = re.match(r"`{3,}", line).group()
            for snippet_line in lines:
                if snippet_line == fence:
                    break
    if not changes:
        raise ValueError("No rule sections found; expected a ruling-diff-comment Markdown report")
    return list(changes.values())


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
        config = json.loads(config_path.read_text(encoding="utf-8"))
        metadata_path = config.get("rules-metadata-path") if isinstance(config, dict) else None
        if not isinstance(metadata_path, str) or not metadata_path.strip():
            raise ValueError(f"Missing or invalid rules-metadata-path in {config_path}")
        metadata_root = (config_path.parent / metadata_path).resolve()
        if not metadata_root.is_relative_to(repository):
            raise ValueError(f"Metadata path escapes repository in {config_path}")
        searched.append(str(metadata_root))
        html_path = (metadata_root / f"{rule_key}.html").resolve()
        json_path = (metadata_root / f"{rule_key}.json").resolve()
        if not all(path.is_relative_to(repository) for path in (html_path, json_path)):
            raise ValueError(f"Rule metadata escapes repository for {rule_key}")
        if not html_path.is_file() or not json_path.is_file():
            continue
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError(f"Rule metadata must be a JSON object: {json_path}")
        if metadata.get("sqKey", rule_key) != rule_key:
            raise ValueError(f"Rule key mismatch in {json_path}: expected {rule_key}")
        matches.append({
            "sonarpedia_path": str(config_path.relative_to(repository)),
            "html_path": str(html_path.relative_to(repository)),
            "json_path": str(json_path.relative_to(repository)),
            "html": html_path.read_text(encoding="utf-8"),
            "json": metadata,
        })
    if not matches:
        raise ValueError(f"No HTML/JSON metadata pair for {rule_key}. Searched: {', '.join(searched)}")
    if len(matches) > 1:
        paths = ", ".join(match["sonarpedia_path"] for match in matches)
        raise ValueError(f"Ambiguous metadata for {rule_key}: {paths}. Select one with --sonarpedia")
    return matches[0]


def prepare_inputs(comment: str, repository: Path, explicit: Path | None = None) -> list[dict]:
    repository = repository.resolve()
    if not repository.is_dir():
        raise ValueError(f"Analyzer repository does not exist: {repository}")
    changes = parse_comment(comment)
    configurations = find_configurations(repository, explicit)
    return [
        {**asdict(change), "metadata": load_rule_metadata(repository, configurations, change.rule_key)}
        for change in changes
    ]
