import argparse
import json
import os
import re
from dataclasses import asdict

from pvf_comment_payload import PvfCommentPayload

PVF_PREFIX = '/pvf'
PVF_COMMAND_REGEX = re.compile(rf"^{re.escape(PVF_PREFIX)}(?:\s+(?P<payload>.*))?$")

# Primary patterns
rule_regex = re.compile(r"\bS\d+\b", re.IGNORECASE)
fps_regex = re.compile(r"\bfps\b", re.IGNORECASE)
all_regex = re.compile(r"\ball\b|\*", re.IGNORECASE)

# Construct language pattern excluding primary patterns
rule_p = rule_regex.pattern
fps_p = fps_regex.pattern
language_regex = re.compile(
    rf"(?!{rule_p})(?!{fps_p})(?!\ball\b)(?<![\w+#-])[a-zA-Z_][\w+#-]*(?![\w+#-])",
    re.IGNORECASE
)


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--comment", required=True, help="Comment to parse")
    args = arg_parser.parse_args()

    output_path = os.environ.get("GITHUB_OUTPUT")

    for line in args.comment.splitlines():
        if (extracted := _extract_pvf_payload(line)) is not None:
            payload = _parse_payload(extracted)
            print(payload)
            _write_github_outputs(payload, output_path)
            return

    _write_github_outputs(None, output_path)


def _extract_pvf_payload(line: str) -> str | None:
    """
    Extract the /pvf command payload from a single line.
    :param line: One line of PR description or comment text.
    :return: Tokens after ``/pvf``, or ``""`` for a bare ``/pvf`` line; ``None`` if not a /pvf command.
    """
    stripped: str = line.lstrip(" \t")
    match = PVF_COMMAND_REGEX.match(stripped)
    if match is None:
        return None
    return (match.group("payload") or "").strip()


def _parse_payload(payload: str) -> PvfCommentPayload:
    languages = language_regex.findall(payload)
    fps = fps_regex.findall(payload)
    all_flags = all_regex.findall(payload)

    if all_flags:
        rules = []
    else :
        rules = [rule.upper() for rule in rule_regex.findall(payload)]

    return PvfCommentPayload(
        rules=rules,
        languages=languages,
        fps=bool(fps),
        all_flag=bool(all_flags)
    )


def _write_github_outputs(payload: PvfCommentPayload | None, output_path: str | None) -> None:
    """
    Write composite-action outputs to ``GITHUB_OUTPUT``.
    :param payload: Parsed payload, or ``None`` when no /pvf command was found.
    :param output_path: Path to the ``GITHUB_OUTPUT`` file.
    """
    if not output_path:
        return

    with open(output_path, "a", encoding="utf-8") as handle:
        if payload is None:
            handle.write("found=false\n")
            handle.write("payload={}\n")
            handle.write("rules-request=\n")
            handle.write("fps=false\n")
            handle.write("languages=[]\n")
            return

        rules_request = "" if payload.all_flag or not payload.rules else ",".join(payload.rules)
        languages_json = json.dumps(payload.languages, separators=(",", ":"))
        handle.write("found=true\n")
        handle.write(f"rules-request={rules_request}\n")
        handle.write(f"fps={'true' if payload.fps else 'false'}\n")
        handle.write(f"languages={languages_json}\n")


if __name__ == '__main__':
    main()
