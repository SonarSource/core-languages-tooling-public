"""Report format selection and parsing, independent of Git and GitHub I/O.

SARIF uses the same per-project, per-rule layout as legacy JSON. Only source
filenames and primary location ranges participate in issue comparison.
"""
from __future__ import annotations

import json
from enum import Enum

from ruling_diff_core_lib.models_and_constants import IssueLocation, RulingReport, SarifReport


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


def parse_ruling_report(content: str, path: str, ref: str) -> RulingReport:
    _, report_format = split_report_filename(path)
    if report_format is ReportFormat.SARIF:
        return parse_sarif_report(content, path, ref)
    return parse_ruling_json(content, path, ref)


def parse_sarif_report(content: str, path: str, ref: str) -> SarifReport:
    """Extract primary locations; rule identity comes from the report filename."""
    context = f"SARIF ruling file {path} at {ref}"
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in {path} at {ref}: {exc}") from exc
    report = require_object(data, context)
    runs = require_list(report.get("runs"), f"{context}: runs")
    normalized: SarifReport = {}
    for run in runs:
        results = require_list(require_object(run, context).get("results", []), f"{context}: results")
        for result in results:
            locations = require_list(
                require_object(result, context).get("locations"), f"{context}: locations"
            )
            if not locations:
                raise ValueError(f"{context}: result must have a source location")
            for location in locations:
                filename, region = parse_sarif_location(location, context)
                normalized.setdefault(filename, []).append(region)
    return normalized


def require_object(value: object, context: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{context}: expected an object")
    return value


def require_list(value: object, context: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{context}: expected an array")
    return value


def parse_sarif_location(location: object, context: str) -> tuple[str, IssueLocation]:
    physical = require_object(
        require_object(location, context).get("physicalLocation"), f"{context}: physicalLocation"
    )
    artifact = require_object(physical.get("artifactLocation"), f"{context}: artifactLocation")
    filename = artifact.get("uri")
    if not isinstance(filename, str) or not filename:
        raise ValueError(f"{context}: artifactLocation.uri must be a non-empty filename")
    region = require_object(physical.get("region", {}), f"{context}: region")
    coordinates: dict[str, int] = {}
    for name in ("startLine", "startColumn", "endLine", "endColumn"):
        # Match LITS IssueLocation: a missing endLine denotes a single-line range.
        default = coordinates.get("startLine", 0) if name == "endLine" else 0
        value = region.get(name, default)
        if name in region and (type(value) is not int or value < 1):
            raise ValueError(f"{context}: {name} must be a positive integer")
        coordinates[name] = value
    return filename, IssueLocation(
        start_line=coordinates["startLine"],
        start_column=coordinates["startColumn"],
        end_line=coordinates["endLine"],
        end_column=coordinates["endColumn"],
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
