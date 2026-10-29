from __future__ import annotations

from ruling_diff_core_lib.models_and_constants import (
    IssueDiff,
    IssueLocation,
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
    lines: OptionalSourceLines, issue_line: int, context: int = SNIPPET_CONTEXT
) -> str:
    if lines is None:
        return "(source file not found at this revision)"
    if issue_line == 0:
        return render_file_level_snippet(lines, context)
    return render_line_snippet(lines, issue_line, context)


def render_file_level_snippet(lines: SourceLines, context: int) -> str:
    if not lines:
        return ">>> FILE-LEVEL ISSUE\n(empty file)"
    end = min(len(lines), 1 + (2 * context))
    content = [f"    {index:>6} | {lines[index - 1]}" for index in range(1, end + 1)]
    return "\n".join([">>> FILE-LEVEL ISSUE", *content])


def render_line_snippet(lines: SourceLines, issue_line: int, context: int) -> str:
    if not lines:
        return f">>> ISSUE HERE (line {issue_line})\n(empty file)"
    clamped_line = max(1, min(issue_line, len(lines)))
    prefix = []
    if issue_line != clamped_line:
        prefix.append(
            f"(requested line {issue_line} not present, showing closest line {clamped_line})"
        )
    body = render_line_window(lines, clamped_line, context)
    return "\n".join(prefix + body)


def render_line_window(lines: SourceLines, center_line: int, context: int) -> list[str]:
    start = max(1, center_line - context)
    end = min(len(lines), center_line + context)
    rendered: list[str] = []
    for number in range(start, end + 1):
        marker = ">>>" if number == center_line else "   "
        rendered.append(f"{marker} {number:>6} | {lines[number - 1]}")
    return rendered


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
    lines = load_source_lines_with_cache(source_cache, source_path)
    body = (
        f"(source file not found in checkout: {file_path})"
        if lines is None
        else render_snippet(lines, location.start_line)
    )
    return Snippet(
        file_path=file_path,
        change_kind=change_kind,
        body=body,
        location=location,
    )


def load_source_lines_with_cache(
    cache: SourceCache,
    path: str,
) -> OptionalSourceLines:
    if path not in cache:
        try:
            content = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            cache[path] = None
        else:
            cache[path] = content.splitlines()
    return cache[path]
