from __future__ import annotations

from html import escape

from ruling_diff_core_lib.comment_rendering import (
    format_comment,
    format_comment_header,
    format_snippet_block,
)
from ruling_diff_core_lib.models_and_constants import COMMENT_SOFT_LIMIT, RuleDiff, Snippet


OPINION_ORDER = {"very_negative": 0, "negative": 1, "neutral": 2, "positive": 3}


def format_opinion(opinion: str) -> str:
    icon = {"very_negative": "🔴", "negative": "🔴", "neutral": "🟡", "positive": "🟢"}[opinion]
    return f"{icon} {opinion.replace('_', ' ')}"


def table_text(value: str) -> str:
    return escape(value).replace("|", "&#124;").replace("\n", " ")


def change_counts(rule_diffs: list[RuleDiff]) -> tuple[int, int]:
    removed = sum(len(diff.removed_locations) for rule in rule_diffs for diff in rule.file_diffs)
    added = sum(len(diff.added_locations) for rule in rule_diffs for diff in rule.file_diffs)
    return removed, added


def overview_row(
    rule_diffs: list[RuleDiff], report: dict | None, anchor: str | None,
) -> str:
    rule = rule_diffs[0]
    label = table_text(f"{rule.repo}:{rule.rule_key}")
    if anchor:
        label = f"[{label}](#{anchor})"
    projects = ", ".join(dict.fromkeys(table_text(diff.project) for diff in rule_diffs))
    removed, added = change_counts(rule_diffs)
    assessment = format_opinion(report["opinion"]) if report else "Not reviewed"
    confidence = report["confidence"] if report else "—"
    return f"| {label} | {projects} | {removed} / {added} | {assessment} | {confidence} |"


def take_selection(project: str, snippet: Snippet, selections: list[dict]) -> dict | None:
    for index, selection in enumerate(selections):
        if (
            selection["project"] == project
            and selection["file_path"] == snippet.file_path
            and selection["change_kind"] == snippet.change_kind
            and selection["line_number"] == snippet.location.start_line
            and selection["snippet"] == snippet.body
            and selection.get("message", "") == snippet.location.message
        ):
            return selections.pop(index)
    return None


def format_rule_group(
    rule_diffs: list[RuleDiff], report: dict | None, anchor: str, limit: int | None = None,
) -> str:
    """Render a rule section of at most `limit` characters (no cap if `limit` is None).

    Selected examples come first. Examples that do not fit are discarded and an omission
    notice, whose size is reserved in the limit, is added to the section.
    """
    rule = rule_diffs[0]
    removed, added = change_counts(rule_diffs)
    projects = ", ".join(escape(diff.project) for diff in rule_diffs)
    assessment = (
        f"{format_opinion(report['opinion'])} | **Confidence:** {report['confidence']}"
        if report else "⚠️ Not automatically assessed"
    )
    heading = (
        f"### {escape(rule.repo)}:{rule.rule_key}\n"
        f"**Projects:** {projects} · **Removed:** {removed} · **Added:** {added}"
        f" · **Automated assessment:** {assessment}"
    )
    lines = [
        f'<a name="{anchor}"></a>',
        heading, "",
    ]
    if report:
        lines.extend([
            report["summary"], "",
        ])
    else:
        lines.extend(["No automated review available for this rule.", ""])
    selections = list(report["selected_examples"]) if report else []
    examples = [
        (diff.project, snippet, take_selection(diff.project, snippet, selections))
        for diff in rule_diffs
        for snippet in diff.snippets
    ]
    examples.sort(key=lambda example: example[2] is None)
    total_examples = len(examples)

    def summary_line(shown: int) -> str:
        return f"<summary>Source examples — {shown} of {removed + added} changed findings shown</summary>"

    def omission_notice(shown: int) -> str:
        return f"{total_examples - shown} source examples omitted because the comment is too large."

    def example_lines(project: str, snippet: Snippet, selection: dict | None, new_project: bool) -> list[str]:
        block: list[str] = [f"#### {escape(project)}", ""] if new_project else []
        if selection:
            label = selection["classification"].replace("_", " ").capitalize()
            block.extend([f"**Automated selection: {label}**", "", selection["rationale"], ""])
        block.extend([format_snippet_block(snippet), ""])
        return block

    empty_projects: list[str] = []
    for diff in rule_diffs:
        if not diff.snippets:
            empty_projects.extend([
                f"#### {escape(diff.project)}", "",
                "No source snippets available for this project.", "",
            ])

    def render(body: list[str], shown: int) -> str:
        parts = [*lines, "<details>", summary_line(shown), "", *body, *empty_projects]
        if shown < total_examples:
            parts.extend([omission_notice(shown), ""])
        parts.append("</details>")
        return "\n".join(parts)

    body: list[str] = []
    current_project = None
    shown = 0
    for project, snippet, selection in examples:
        candidate = body + example_lines(project, snippet, selection, project != current_project)
        if limit is not None and len(render(candidate, shown + 1)) > limit:
            break
        body = candidate
        current_project = project
        shown += 1
    return render(body, shown)


def format_reviewed_comment(rule_diffs: list[RuleDiff], reports: list[dict]) -> str:
    if not rule_diffs:
        return format_comment(rule_diffs)
    grouped: dict[tuple[str, str], list[RuleDiff]] = {}
    for rule in rule_diffs:
        grouped.setdefault((rule.repo, rule.rule_key), []).append(rule)
    reviews = {(report["repository"], report["rule_key"]): report for report in reports}
    keys = sorted(grouped, key=lambda key: (
        OPINION_ORDER.get(reviews.get(key, {}).get("opinion"), 4), key,
    ))
    anchors = {key: f"ruling-rule-{index + 1}" for index, key in enumerate(keys)}
    header = format_comment_header(rule_diffs) + "\n## Rule overview\n\n"
    table_header = (
        "| Rule | Projects | Removed / added | Automated assessment | Confidence |\n"
        "| --- | --- | ---: | --- | --- |\n"
    )
    advisory = "\n\nAutomated assessments are advisory; confidence is not a correctness guarantee.\n\n"
    overview_notice = "\n\nSome rules are omitted from the overview because the comment is too large."
    omission_notice = f"\n\n{len(keys)} rule sections omitted because the comment is too large."
    rows: list[str] = []
    for key in keys:
        row = overview_row(grouped[key], reviews.get(key), anchors[key])
        candidate = header + table_header + "\n".join(rows + [row])
        if len(candidate + overview_notice + advisory + omission_notice) > COMMENT_SOFT_LIMIT:
            break
        rows.append(row)
    if not rows:
        return format_comment(rule_diffs)
    overview_tail = overview_notice if len(rows) < len(keys) else ""
    intro = header + table_header + "\n".join(rows) + overview_tail + advisory
    sections: list[str] = []
    for key in keys:
        report = reviews.get(key)
        # Remaining budget for this section, keeping room for the separator before it
        # and for the trailing omission notice.
        used = len(intro) + len("\n\n".join(sections)) + (2 if sections else 0)
        limit = COMMENT_SOFT_LIMIT - used - len(omission_notice)
        section = format_rule_group(grouped[key], report, anchors[key], limit)
        if report and len(section) > limit:
            compact_report = {
                **report,
                "summary": "Automated review omitted because it exceeds the comment size limit.",
                "selected_examples": [],
            }
            section = format_rule_group(grouped[key], compact_report, anchors[key], limit)
        if len(section) > limit:
            break
        sections.append(section)
    rows = [
        overview_row(grouped[key], reviews.get(key), anchors[key] if index < len(sections) else None)
        for index, key in enumerate(keys[:len(rows)])
    ]
    comment = header + table_header + "\n".join(rows) + overview_tail + advisory + "\n\n".join(sections)
    if len(sections) < len(keys):
        comment += f"\n\n{len(keys) - len(sections)} rule sections omitted because the comment is too large."
    return comment
