from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from ruling_diff_inputs import prepare_inputs


def positive_integer(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review ruling diffs with local rule metadata and DSPy")
    parser.add_argument("comment", type=Path, help="Path to a ruling-diff-comment Markdown file")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Analyzer repository root (default: cwd)")
    parser.add_argument("--sonarpedia", type=Path, help="Select one config, relative to --repo or absolute")
    parser.add_argument("--model", default=os.environ.get("DSPY_MODEL"), help="DSPy provider/model (or DSPY_MODEL)")
    parser.add_argument("--api-base", default=os.environ.get("DSPY_API_BASE"), help="Optional model endpoint")
    parser.add_argument("--max-examples", type=positive_integer, default=3)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write to a file instead of stdout")
    parser.add_argument("--prepare-only", action="store_true", help="Print gathered inputs as JSON without importing DSPy or calling a model")
    args = parser.parse_args()
    if not args.prepare_only and not args.model:
        parser.error("--model or DSPY_MODEL is required unless --prepare-only is set")
    return args


def render_markdown(reports: list[dict]) -> str:
    sections = ["## AI Ruling Diff Review", "", "AI-assisted triage, not a correctness verdict. Confidence is not calibrated."]
    for report in reports:
        sections.extend([
            "", f"### {report['repository']}:{report['rule_key']}", "",
            f"**Opinion:** {report['opinion'].replace('_', ' ')} | **Confidence:** {report['confidence']}",
            "", report["summary"], "",
            f"Evidence: {report['available_examples']} visible examples; "
            f"{report['added_count']} total added, {report['removed_count']} total removed issues.",
            f"Metadata: `{report['metadata_paths']['json_path']}` and `{report['metadata_paths']['html_path']}`.",
        ])
        for example in report["selected_examples"]:
            location = f"line {example['line_number']}" if example["line_number"] else "file-level"
            longest_fence = max((len(match) for match in re.findall(r"`+", example["snippet"])), default=0)
            fence = "`" * max(3, longest_fence + 1)
            sections.extend([
                "", f"#### {example['classification'].replace('_', ' ')} — {example['example_id']}", "",
                f"**{example['change_kind'].title()}** `{example['project']}/{example['file_path']}` ({location})",
                "", example["rationale"], "", f"{fence}{example['language']}", example["snippet"], fence,
            ])
    return "\n".join(sections)


def main() -> int:
    args = parse_args()
    try:
        inputs = prepare_inputs(args.comment.read_text(encoding="utf-8"), args.repo, args.sonarpedia)
        if args.prepare_only:
            output = json.dumps(inputs, indent=2, ensure_ascii=False)
        else:
            import dspy
            from ruling_diff_predictor import ReviewRulingChange, review_changes

            dspy.configure_cache(enable_disk_cache=False, enable_memory_cache=False)
            options = {"api_base": args.api_base} if args.api_base else {}
            lm = dspy.LM(args.model, cache=False, **options)
            with dspy.context(lm=lm):
                reports = review_changes(inputs, dspy.Predict(ReviewRulingChange), args.max_examples)
            output = json.dumps(reports, indent=2, ensure_ascii=False) if args.format == "json" else render_markdown(reports)
        if args.output:
            args.output.write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
    except (OSError, ValueError, ImportError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
