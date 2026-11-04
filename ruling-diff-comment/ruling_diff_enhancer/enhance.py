from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from .ruling_diff_inputs import prepare_inputs
from .ruling_diff_models import model_connection
from .rendering import format_opinion


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
    parser.add_argument("--model", default=os.environ.get("DSPY_MODEL"), help="Model name or DSPy provider/model (or DSPY_MODEL)")
    parser.add_argument(
        "--provider", choices=("auto", "direct", "portkey"),
        default=os.environ.get("DSPY_PROVIDER", "auto"),
        help="Connection mode (or DSPY_PROVIDER); auto uses Portkey only without a custom API base",
    )
    parser.add_argument("--api-base", default=os.environ.get("DSPY_API_BASE"), help="Optional model endpoint")
    parser.add_argument("--max-examples", type=positive_integer, choices=range(1, 4), default=3)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write to a file instead of stdout")
    parser.add_argument("--prepare-only", action="store_true", help="Print gathered inputs as JSON without importing DSPy or calling a model")
    args = parser.parse_args()
    if not args.prepare_only and not args.model:
        parser.error("--model or DSPY_MODEL is required unless --prepare-only is set")
    return args


def render_markdown(reports: list[dict]) -> str:
    sections = ["## Automated Ruling Diff Review", ""]
    for report in reports:
        opinion = format_opinion(report['opinion'])
        confidence = report['confidence']

        sections.extend([
            "", "<details>",
            f"<summary><b>Rule:</b> {report['repository']}:{report['rule_key']} | <b>Opinion:</b> {opinion} | <b>Confidence:</b> {confidence} </summary>",
            "", report["summary"]
        ])
        for example in report["selected_examples"]:
            location = f"line {example['line_number']}" if example["line_number"] else "file-level"
            longest_fence = max((len(match) for match in re.findall(r"`+", example["snippet"])), default=0)
            fence = "`" * max(3, longest_fence + 1)
            file_location =  f"`{example['project']}/{example['file_path']}` ({location})"
            sections.extend([
                "", f"**{example['classification'].replace('_', ' ').capitalize()}** {file_location}",
                "", example["rationale"], "", f"{fence}{example['language']}", example["snippet"], fence,
            ])
        sections.append("</details>")
    return "\n".join(sections)


def review_comment(
    comment: str, repository: Path, *, model: str, provider: str = "auto",
    api_base: str | None = None, sonarpedia: Path | None = None,
    max_examples: int = 3,
) -> list[dict]:
    inputs = prepare_inputs(comment, repository, sonarpedia)
    resolved_model, options = model_connection(model, provider, api_base)
    import dspy
    from .ruling_diff_predictor import ReviewRulingChange, review_changes

    dspy.configure_cache(enable_disk_cache=False, enable_memory_cache=False)
    lm = dspy.LM(resolved_model, cache=False, **options)
    with dspy.context(lm=lm):
        return review_changes(inputs, dspy.Predict(ReviewRulingChange), max_examples)


def read_comment(path: Path, repository: Path) -> str:
    resolved_repository = repository.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_repository) or not resolved_path.is_file():
        raise ValueError(f"Comment path must be a file inside {resolved_repository}: {path}")
    return resolved_path.read_text(encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        comment = read_comment(args.comment, args.repo)
        if args.prepare_only:
            inputs = prepare_inputs(comment, args.repo, args.sonarpedia)
            output = json.dumps(inputs, indent=2, ensure_ascii=False)
        else:
            reports = review_comment(
                comment, args.repo, model=args.model, provider=args.provider,
                api_base=args.api_base, sonarpedia=args.sonarpedia,
                max_examples=args.max_examples,
            )
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
