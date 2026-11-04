from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IssueLocation:
    start_line: int = 0
    # Zero represents an unspecified coordinate (SARIF coordinates start at 1).
    start_column: int = 0
    end_line: int = 0
    end_column: int = 0
    message: str = ""

    def __post_init__(self) -> None:
        for name in ("start_line", "start_column", "end_line", "end_column"):
            if type(getattr(self, name)) is not int:
                raise TypeError(f"{name} must be an integer")

    def sort_key(self) -> tuple[int, int, int, int, str]:
        return (
            self.start_line,
            self.start_column,
            self.end_line,
            self.end_column,
            self.message,
        )


SarifReport = dict[str, list[IssueLocation]]
OptionalSarifReport = SarifReport | None
SourceLines = list[str]
OptionalSourceLines = SourceLines | None
SourceCache = dict[str, OptionalSourceLines]


class RulingDiffIO(Protocol):
    ruling_root: str | None
    sources_root: str

    def load_sarif_at_ref(self, path: str, ref: str) -> OptionalSarifReport:
        ...

    def resolve_source_path(self, project: str, file_path: str) -> str:
        ...

EXPECTED_RULING_ROOTS = (
    "its/ruling/src/test/resources/expected",
    "private/its/ruling/src/test/resources/expected",
    "private/its-enterprise/ruling/src/test/resources/expected",
)
EXPECTED_RULING_ROOT = EXPECTED_RULING_ROOTS[0]
COMMENT_MARKER = "<!-- ruling-diff-comment -->"
COMMENT_SOFT_LIMIT = 60000
SNIPPET_CONTEXT = 5
MAX_SNIPPETS_PER_FILE = 3
MAX_SNIPPETS_PER_RULE = 15

# This is specific for sonar-python-enterprise and ultimately should go away
PROJECT_SOURCE_OVERRIDES = {
    "sources_internal_ruling": "private/its-enterprise/sources_internal_ruling",
    "namespace_basic": "private/its-enterprise/sources_internal_namespace_ruling/basic_namespace",
    "namespace_mixed": "private/its-enterprise/sources_internal_namespace_ruling/mixed_namespace",
}


@dataclass(frozen=True)
class IssueDiff:
    file_path: str
    added_locations: list[IssueLocation]
    removed_locations: list[IssueLocation]


@dataclass(frozen=True)
class Snippet:
    file_path: str
    location: IssueLocation
    change_kind: str
    body: str


@dataclass(frozen=True)
class RuleDiff:
    project: str
    repo: str
    rule_key: str
    file_diffs: list[IssueDiff]
    snippets: list[Snippet]
    is_new_file: bool
    is_deleted_file: bool
