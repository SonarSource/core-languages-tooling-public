from __future__ import annotations

from pathlib import Path

from ruling_diff_core_lib.models_and_constants import (
    IssueDiff,
    IssueLocation,
    PROJECT_SOURCE_OVERRIDES,
    MAX_SNIPPETS_PER_FILE,
    MAX_SNIPPETS_PER_RULE,
    SNIPPET_CONTEXT,
    OptionalSourceLines,
    RulingDiffIO,
    Snippet,
    SourceCache,
    SourceLines,
)


def render_snippet(
    lines: OptionalSourceLines,
    location: IssueLocation,
    context: int = SNIPPET_CONTEXT,
) -> str:
    if lines is None:
        return "(source file not found at this revision)"
    if location.start_line == 0:
        return render_file_level_snippet(lines, context)
    return render_line_snippet(lines, location, context)


def render_file_level_snippet(lines: SourceLines, context: int) -> str:
    if not lines:
        return ">>> FILE-LEVEL ISSUE\n(empty file)"
    end = min(len(lines), 1 + (2 * context))
    content = [f"    {index:>6} | {lines[index - 1]}" for index in range(1, end + 1)]
    return "\n".join([">>> FILE-LEVEL ISSUE", *content])


def render_line_snippet(
    lines: SourceLines,
    location: IssueLocation,
    context: int = SNIPPET_CONTEXT,
) -> str:
    issue_line = location.start_line
    if not lines:
        return f">>> ISSUE HERE (line {issue_line})\n(empty file)"
    clamped_line = max(1, min(issue_line, len(lines)))
    prefix = []
    if issue_line != clamped_line:
        prefix.append(
            f"(requested line {issue_line} not present, showing closest line {clamped_line})"
        )
    body = render_line_window(lines, clamped_line, context, location)
    return "\n".join(prefix + body)


def render_line_window(
    lines: SourceLines,
    center_line: int,
    context: int,
    location: IssueLocation,
) -> list[str]:
    start = max(1, center_line - context)
    end = min(len(lines), center_line + context)
    rendered: list[str] = []
    for number in range(start, end + 1):
        marker = ">>>" if number == center_line else "   "
        prefix = f"{marker} {number:>6} | "
        source_line = lines[number - 1]
        rendered.append(prefix + expand_source_tabs(source_line, len(prefix)))
        underline = render_issue_underline(source_line, prefix, number, location)
        if underline is not None:
            rendered.append(underline)
    return rendered


def render_issue_underline(
    source_line: str, prefix: str, number: int, location: IssueLocation
) -> str | None:
    if location.start_column == 0 or not (
        location.start_line <= number <= (location.end_line or location.start_line)
    ):
        return None

    # SARIF columns are 1-based UTF-16 offsets, with an exclusive end column.
    line_length = sum(2 if ord(char) > 0xFFFF else 1 for char in source_line)
    start_column = location.start_column if number == location.start_line else 1
    end_column = min(
        underline_end_column(number, location, start_column, line_length),
        line_length + 1,
    )
    if start_column > line_length or end_column <= start_column:
        return None

    return " " * len(prefix) + underline_marks(
        source_line, len(prefix), start_column, end_column
    )


def underline_end_column(
    number: int, location: IssueLocation, start_column: int, line_length: int
) -> int:
    if number == (location.end_line or location.start_line):
        if location.end_column:
            return location.end_column
        if number == location.start_line:
            return start_column + 1
    return line_length + 1


def underline_marks(
    source_line: str, prefix_width: int, start_column: int, end_column: int
) -> str:
    marks = ""
    column = 1
    visual_column = prefix_width
    for char in source_line:
        if column >= end_column:
            break
        utf16_width = 2 if ord(char) > 0xFFFF else 1
        visual_width = 8 - visual_column % 8 if char == "\t" else utf16_width
        marks += ("^" if column + utf16_width > start_column else " ") * visual_width
        column += utf16_width
        visual_column += visual_width
    return marks


def expand_source_tabs(source_line: str, prefix_width: int) -> str:
    expanded = ""
    visual_column = prefix_width
    for char in source_line:
        width = 2 if ord(char) > 0xFFFF else 1
        if char == "\t":
            width = 8 - visual_column % 8
            expanded += " " * width
        else:
            expanded += char
        visual_column += width
    return expanded


def build_snippets_for_rule(
    project: str,
    file_diffs: list[IssueDiff],
    source_cache: SourceCache,
    io: RulingDiffIO,
) -> list[Snippet]:
    snippets: list[Snippet] = []
    for file_diff in file_diffs:
        snippets.extend(
            collect_snippets_for_file(
                project=project,
                file_diff=file_diff,
                source_cache=source_cache,
                io=io,
            )
        )
        if len(snippets) >= MAX_SNIPPETS_PER_RULE:
            break
    return snippets[:MAX_SNIPPETS_PER_RULE]


def collect_snippets_for_file(
    *,
    project: str,
    file_diff: IssueDiff,
    source_cache: SourceCache,
    io: RulingDiffIO,
) -> list[Snippet]:
    snippets: list[Snippet] = []
    for change_kind, locations in (
        ("removed", file_diff.removed_locations),
        ("added", file_diff.added_locations),
    ):
        for location in list(dict.fromkeys(locations))[:MAX_SNIPPETS_PER_FILE]:
            snippets.append(
                create_issue_snippet(
                    project=project,
                    file_path=file_diff.file_path,
                    change_kind=change_kind,
                    source_cache=source_cache,
                    io=io,
                    location=location,
                )
            )
    return snippets


def create_issue_snippet(
    *,
    project: str,
    file_path: str,
    change_kind: str,
    source_cache: SourceCache,
    io: RulingDiffIO,
    location: IssueLocation,
) -> Snippet:
    source_path = io.resolve_source_path(project, file_path)
    source_root = (
        io.sources_root
        if project == "project"
        else PROJECT_SOURCE_OVERRIDES.get(project, f"{io.sources_root}/{project}")
    )
    lines = load_source_lines_with_cache(source_cache, source_path, source_root)
    body = (
        f"(source file not found in checkout: {file_path})"
        if lines is None
        else render_snippet(lines, location)
    )
    return Snippet(
        file_path=file_path,
        change_kind=change_kind,
        body=body,
        location=location,
    )


def load_source_lines_with_cache(
    cache: SourceCache, path: str, source_root: str
) -> OptionalSourceLines:
    if path not in cache:
        resolved = Path(path).resolve()
        root = Path(source_root).resolve()
        if not resolved.is_relative_to(root):
            cache[path] = None
            return None
        try:
            content = resolved.read_text(encoding="utf-8")
        except FileNotFoundError:
            cache[path] = None
        else:
            cache[path] = content.splitlines()
    return cache[path]
