import argparse
import json
import os
import re

from pvf_comment_payload import PvfCommentPayload

PVF_COMMAND_PREFIX = '/pvf'
SEPARATORS = ' ', ',', '\t'
ALL = "ALL", "all", '*'
FPS = "FPS", "fps"


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--comment", required=True, help="Comment to parse")
    arg_parser.add_argument("--rule-prefix", required=True, help="Prefix for rule keys (e.g., 'S')")
    args = arg_parser.parse_args()

    output_path = os.environ.get("GITHUB_OUTPUT")

    for line in args.comment.splitlines():
        if (extracted := _extract_pvf_payload(line)) is not None:
            payload = _parse_payload(extracted, args.rule_prefix)
            print(payload)
            _write_github_outputs(payload, output_path)
            return

    _write_github_outputs(None, output_path)


def _extract_pvf_payload(line: str) -> list[str] | None:
    """
    Extract the /pvf command payload from a single line.
    :param line: One line of PR description or comment text.
    :return: Tokens after ``/pvf``, or ``""`` for a bare ``/pvf`` line; ``None`` if not a /pvf command.
    """
    stripped: str = line.lstrip(" \t")

    # python split doesn't accept multiple separators, so we normalize to the first separator
    for sep in SEPARATORS[1:]:
        stripped = stripped.replace(sep, SEPARATORS[0])

    tokens = [t for t in stripped.split(SEPARATORS[0]) if t]

    if tokens and tokens[0] == PVF_COMMAND_PREFIX:
        return tokens[1:]
    return None


def _parse_payload(payload: list[str], rule_prefix: str) -> PvfCommentPayload:
    def has_flag(matchers: tuple[str]) -> bool:
        return any(t in matchers for t in payload)

    rule_prefix = rule_prefix.upper()

    all_flag = has_flag(ALL)
    fps = has_flag(FPS)
    used = {*ALL, *FPS}
    rules = [tu for t in payload if (tu := t.upper()).startswith(rule_prefix) and t not in used]
    used = used | set(rules)
    languages = [t for t in payload if t not in used]

    if all_flag:
        rules = []
    elif not rules:
        all_flag = True

    return PvfCommentPayload(
        rules=rules,
        languages=languages,
        fps=fps,
        all_flag=all_flag
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
