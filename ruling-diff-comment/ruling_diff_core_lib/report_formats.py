"""Report format selection and parsing, independent of Git and GitHub I/O.

SARIF uses the same per-project, per-rule layout as legacy JSON. Its parser
is deliberately unimplemented until the ruling SARIF fields are agreed.
"""
from __future__ import annotations

import json
from enum import Enum

from ruling_diff_core_lib.models_and_constants import RulingJson


class ReportFormat(Enum):
    JSON = "json"
    SARIF = "sarif"


REPORT_SUFFIXES = (
    (".sarif", ReportFormat.SARIF),
    (".json", ReportFormat.JSON),
)


def split_report_filename(path: str) -> tuple[str, ReportFormat]:
    """Return the filename without its report suffix and the selected format."""
    for suffix, report_format in REPORT_SUFFIXES:
        if path.endswith(suffix):
            return path[:-len(suffix)], report_format
    raise ValueError(f"Unsupported ruling report extension: {path}")


def parse_ruling_report(content: str, path: str, ref: str) -> RulingJson:
    _, report_format = split_report_filename(path)
    if report_format is ReportFormat.SARIF:
        return parse_sarif_report(content, path, ref)
    return parse_ruling_json(content, path, ref)


def parse_sarif_report(content: str, path: str, ref: str) -> RulingJson:
    """Extension point for SARIF; do not interpret report fields yet."""
    raise NotImplementedError(
        f"SARIF ruling report processing is not implemented: {path} at {ref}. "
        "The ruling SARIF fields have not been defined yet."
    )


def parse_ruling_json(content: str, path: str, ref: str) -> dict[str, list[int]]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in {path} at {ref}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Ruling file {path} at {ref} must be a JSON object")
    return normalize_ruling_json(data, path, ref)


def normalize_ruling_json(data: dict, path: str, ref: str) -> dict[str, list[int]]:
    # Standard format: source file key -> list of line numbers.
    normalized: dict[str, list[int]] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise ValueError(f"Ruling file {path} at {ref} has non-string key")
        if not isinstance(value, list) or not all(isinstance(v, int) for v in value):
            raise ValueError(
                f"Ruling file {path} at {ref} has non-integer line list for key {key}"
            )
        normalized[key] = value
    return normalized
