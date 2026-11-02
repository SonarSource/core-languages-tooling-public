"""Parse per-project, per-rule SARIF reports independently of Git/GitHub I/O."""
from __future__ import annotations

import json

from ruling_diff_core_lib.models_and_constants import IssueLocation, SarifReport


def parse_sarif_report(content: str, path: str, ref: str) -> SarifReport:
    """Extract primary locations and messages; rule identity comes from the filename."""
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
            result = require_object(result, context)
            message_data = require_object(result.get("message", {}), f"{context}: message")
            message = message_data.get("text", "")
            if not isinstance(message, str):
                raise ValueError(f"{context}: message text must be a string")
            locations = require_list(
                result.get("locations"), f"{context}: locations"
            )
            if not locations:
                raise ValueError(f"{context}: result must have a source location")
            for location in locations:
                filename, region = parse_sarif_location(location, context, message)
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


def parse_sarif_location(
    location: object, context: str, message: str = ""
) -> tuple[str, IssueLocation]:
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
        message=message,
    )

