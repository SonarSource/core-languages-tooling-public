import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


MODULE_DIR = pathlib.Path(__file__).parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import ruling_diff_core as core
import ruling_diff_io as io
from ruling_diff_core_lib import snippet_generation
from ruling_diff_core_lib.snippet_generation import load_source_lines_with_cache


IssueDiff = core.IssueDiff
RuleDiff = core.RuleDiff
Snippet = core.Snippet


class FakeRulingDiffIO:
    def __init__(
        self,
        json_by_ref_path: dict[tuple[str, str], dict[str, list[int]] | None],
        ruling_root: str | None = None,
        sources_root: str = "private/its-enterprise/sources_ruling",
    ) -> None:
        self.json_by_ref_path = json_by_ref_path
        self.ruling_root = ruling_root
        self.sources_root = sources_root
        self.load_json_calls: list[tuple[str, str]] = []
        self.resolve_calls: list[tuple[str, str]] = []

    def load_json_at_ref(self, path: str, ref: str) -> dict[str, list[int]] | None:
        self.load_json_calls.append((path, ref))
        return self.json_by_ref_path.get((path, ref))

    def resolve_source_path(self, project: str, file_path: str) -> str:
        self.resolve_calls.append((project, file_path))
        return f"{self.sources_root}/{project}/{file_path.lstrip('/')}"


class ChangedRulingFilesTest(unittest.TestCase):
    def test_discovers_all_expected_roots(self) -> None:
        standard = "its/ruling/src/test/resources/expected/alpha/java-S100.json"
        enterprise = "private/its/ruling/src/test/resources/expected/beta/java-S200.json"
        python_enterprise = "private/its-enterprise/ruling/src/test/resources/expected/gamma/python-S100.json"
        maven_actual = "its/ruling/target/actual/alpha/java-S300.json"
        gradle_actual = "private/its/ruling/build/actual/beta/java-S300.json"
        obsolete = (
            "private/its-enterprise/ruling/src/test/resources/expected_ruling/"
            "alpha/java-S400.json"
        )
        with patch.object(
            io,
            "run_command",
            return_value="\n".join(
                (enterprise, python_enterprise, maven_actual, gradle_actual, standard, obsolete)
            ),
        ) as run_command:
            changed = io.get_changed_ruling_files("base", "head")

        self.assertEqual(changed, sorted([standard, enterprise, python_enterprise]))
        run_command.assert_called_once_with(
            [
                "git",
                "diff",
                "--name-only",
                "base...head",
                "--",
                "its/ruling/src/test/resources/expected/",
                "private/its/ruling/src/test/resources/expected/",
                "private/its-enterprise/ruling/src/test/resources/expected/",
            ]
        )

    def test_explicit_root_restricts_discovery(self) -> None:
        root = "custom/expected"
        with patch.object(
            io, "run_command", return_value=f"{root}/alpha/java-S100.json"
        ) as run_command:
            changed = io.get_changed_ruling_files("base", "head", root)

        self.assertEqual(changed, [f"{root}/alpha/java-S100.json"])
        run_command.assert_called_once_with(
            ["git", "diff", "--name-only", "base...head", "--", f"{root}/"]
        )


class ParsePathTest(unittest.TestCase):
    def test_parse_standard_ruling_path(self) -> None:
        path = "its/ruling/src/test/resources/expected/airflow/python-S1066.json"
        self.assertEqual(core.parse_ruling_path(path), ("airflow", "python", "S1066"))

    def test_rejects_generated_actual_path(self) -> None:
        with self.assertRaises(ValueError):
            core.parse_ruling_path("its/ruling/target/actual/airflow/python-S1066.json")

    def test_parse_ruling_path(self) -> None:
        path = "private/its/ruling/src/test/resources/expected/airflow/python-S1066.json"
        self.assertEqual(core.parse_ruling_path(path), ("airflow", "python", "S1066"))

    def test_parse_python_enterprise_layout(self) -> None:
        for repository in ("python", "pythonenterprise"):
            with self.subTest(repository=repository):
                path = (
                    "private/its-enterprise/ruling/src/test/resources/expected/"
                    f"specific-rules/{repository}-S7471.json"
                )
                self.assertEqual(core.parse_ruling_path(path), ("specific-rules", repository, "S7471"))

    def test_parse_ruling_path_with_pythonenterprise(self) -> None:
        path = "private/its/ruling/src/test/resources/expected/specific-rules/pythonenterprise-S7471.json"
        self.assertEqual(
            core.parse_ruling_path(path),
            ("specific-rules", "pythonenterprise", "S7471"),
        )

    def test_parse_ruling_path_with_legacy_key(self) -> None:
        path = "private/its/ruling/src/test/resources/expected/scikit-learn/python-LineLength.json"
        self.assertEqual(
            core.parse_ruling_path(path),
            ("scikit-learn", "python", "LineLength"),
        )

    def test_parse_rule_filename_rejects_empty_rule_key(self) -> None:
        with self.assertRaises(ValueError):
            core.parse_rule_filename("python-.json")

    def test_parse_rule_filename_rejects_empty_repository(self) -> None:
        with self.assertRaises(ValueError):
            core.parse_rule_filename("-S1066.json")

    def test_strip_project_key_python_format(self) -> None:
        # Python format: project:path
        self.assertEqual(
            core.strip_project_key("airflow:airflow/cli/cli_parser.py"),
            "airflow/cli/cli_parser.py",
        )

    def test_strip_project_key_java_maven_format_commons_beanutils(self) -> None:
        # Java Maven format: groupId:artifactId:path
        self.assertEqual(
            core.strip_project_key("commons-beanutils:commons-beanutils:src/main/java/org/apache/commons/beanutils2/LazyDynaList.java"),
            "src/main/java/org/apache/commons/beanutils2/LazyDynaList.java",
        )

    def test_strip_project_key_java_maven_format_eclipse_jetty(self) -> None:
        # Java Maven format with module path: groupId:artifactId:module/path
        self.assertEqual(
            core.strip_project_key("org.eclipse.jetty:jetty-project:jetty-http/src/main/java/org/eclipse/jetty/http/QuotedCSVParser.java"),
            "jetty-http/src/main/java/org/eclipse/jetty/http/QuotedCSVParser.java",
        )

    def test_strip_project_key_java_maven_format_test_file(self) -> None:
        # Java Maven format with test file
        self.assertEqual(
            core.strip_project_key("org.eclipse.jetty:jetty-project:jetty-io/src/test/java/org/eclipse/jetty/io/IOTest.java"),
            "jetty-io/src/test/java/org/eclipse/jetty/io/IOTest.java",
        )

    def test_strip_project_key_no_colon(self) -> None:
        # Edge case: no colon in key
        self.assertEqual(
            core.strip_project_key("simple-path/file.py"),
            "simple-path/file.py",
        )

    def test_strip_project_key_no_colon_simple_file(self) -> None:
        # Edge case: simple filename with no path separator
        self.assertEqual(
            core.strip_project_key("file.py"),
            "file.py",
        )


class NormalizeJsonTest(unittest.TestCase):
    def test_normalize_standard_format(self) -> None:
        # Standard format: rule -> list of line numbers
        data = {"S1234": [10, 20, 30]}
        result = io.normalize_ruling_json(data, "test.json", "HEAD")
        self.assertEqual(result, {"S1234": [10, 20, 30]})

    def test_normalize_dotnet_format(self) -> None:
        # .NET format with Issues array
        data = {
            "Issues": [
                {
                    "Id": "S1135",
                    "Message": "Complete the task",
                    "Location": {"StartLine": 270, "StartColumn": 16, "EndLine": 270, "EndColumn": 20}
                },
                {
                    "Id": "S1135",
                    "Message": "Complete the task",
                    "Location": {"StartLine": 54, "StartColumn": 12, "EndLine": 54, "EndColumn": 16}
                },
                {
                    "Id": "S1192",
                    "Message": "Define a constant",
                    "Location": {"StartLine": 100, "StartColumn": 10, "EndLine": 100, "EndColumn": 20}
                }
            ]
        }
        result = io.normalize_ruling_json(data, "test.json", "HEAD")
        # Should group by rule ID and sort line numbers
        self.assertEqual(result, {"S1135": [54, 270], "S1192": [100]})

    def test_normalize_dotnet_format_empty_issues(self) -> None:
        # .NET format with empty Issues array
        data = {"Issues": []}
        result = io.normalize_ruling_json(data, "test.json", "HEAD")
        self.assertEqual(result, {})

    def test_normalize_dotnet_format_non_dict_issue(self) -> None:
        # .NET format with non-dict issue in Issues array
        data = {"Issues": ["not a dict"]}
        with self.assertRaises(ValueError) as ctx:
            io.normalize_ruling_json(data, "test.json", "HEAD")
        self.assertIn("non-dict issue", str(ctx.exception))

    def test_normalize_dotnet_format_missing_id(self) -> None:
        # .NET format with missing Id field
        data = {"Issues": [{"Location": {"StartLine": 10}}]}
        with self.assertRaises(ValueError) as ctx:
            io.normalize_ruling_json(data, "test.json", "HEAD")
        self.assertIn("without string Id", str(ctx.exception))

    def test_normalize_dotnet_format_non_string_id(self) -> None:
        # .NET format with non-string Id field
        data = {"Issues": [{"Id": 123, "Location": {"StartLine": 10}}]}
        with self.assertRaises(ValueError) as ctx:
            io.normalize_ruling_json(data, "test.json", "HEAD")
        self.assertIn("without string Id", str(ctx.exception))

    def test_normalize_dotnet_format_missing_location(self) -> None:
        # .NET format with missing Location field - should default to line 0
        data = {"Issues": [{"Id": "S1234"}]}
        result = io.normalize_ruling_json(data, "test.json", "HEAD")
        self.assertEqual(result, {"S1234": [0]})

    def test_normalize_dotnet_format_non_dict_location(self) -> None:
        # .NET format with non-dict Location field - should default to line 0
        data = {"Issues": [{"Id": "S1234", "Location": "not a dict"}]}
        result = io.normalize_ruling_json(data, "test.json", "HEAD")
        self.assertEqual(result, {"S1234": [0]})

    def test_normalize_dotnet_format_missing_start_line(self) -> None:
        # .NET format with missing StartLine field - should default to line 0
        data = {"Issues": [{"Id": "S1234", "Location": {}}]}
        result = io.normalize_ruling_json(data, "test.json", "HEAD")
        self.assertEqual(result, {"S1234": [0]})

    def test_normalize_dotnet_format_non_int_start_line(self) -> None:
        # .NET format with non-integer StartLine field - should default to line 0
        data = {"Issues": [{"Id": "S1234", "Location": {"StartLine": "10"}}]}
        result = io.normalize_ruling_json(data, "test.json", "HEAD")
        self.assertEqual(result, {"S1234": [0]})


class DiffLogicTest(unittest.TestCase):
    def test_diff_ruling_jsons_added_issues(self) -> None:
        diffs = core.diff_ruling_jsons({"proj:a.py": [1, 2]}, {"proj:a.py": [1, 2, 3]})
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].file_path, "a.py")
        self.assertEqual(diffs[0].added_lines, [3])

    def test_diff_ruling_jsons_removed_issues(self) -> None:
        diffs = core.diff_ruling_jsons({"proj:a.py": [1, 2, 3]}, {"proj:a.py": [1]})
        self.assertEqual(diffs[0].removed_lines, [2, 3])

    def test_diff_ruling_jsons_new_file_entry(self) -> None:
        diffs = core.diff_ruling_jsons(
            {"proj:a.py": [1]},
            {"proj:a.py": [1], "proj:b.py": [5]},
        )
        self.assertEqual(diffs[0].file_path, "b.py")
        self.assertEqual(diffs[0].added_lines, [5])

    def test_diff_ruling_jsons_removed_file_entry(self) -> None:
        diffs = core.diff_ruling_jsons(
            {"proj:a.py": [1], "proj:b.py": [5]},
            {"proj:a.py": [1]},
        )
        self.assertEqual(diffs[0].file_path, "b.py")
        self.assertEqual(diffs[0].removed_lines, [5])

    def test_diff_ruling_jsons_new_ruling_file(self) -> None:
        diffs = core.diff_ruling_jsons(None, {"proj:a.py": [10]})
        self.assertEqual(diffs[0].added_lines, [10])

    def test_diff_ruling_jsons_deleted_ruling_file(self) -> None:
        diffs = core.diff_ruling_jsons({"proj:a.py": [10]}, None)
        self.assertEqual(diffs[0].removed_lines, [10])

    def test_diff_ruling_jsons_no_changes(self) -> None:
        self.assertEqual(
            core.diff_ruling_jsons(
                {"proj:a.py": [10], "proj:b.py": [11, 12]},
                {"proj:a.py": [10], "proj:b.py": [11, 12]},
            ),
            [],
        )

    def test_duplicate_line_numbers_preserved(self) -> None:
        diffs = core.diff_ruling_jsons({"proj:a.py": [297]}, {"proj:a.py": [297, 297]})
        self.assertEqual(diffs[0].added_lines, [297])


class FormattingTest(unittest.TestCase):
    def test_format_comment_single_rule(self) -> None:
        rule_diff = RuleDiff(
            project="airflow",
            repo="python",
            rule_key="S107",
            file_diffs=[IssueDiff("airflow/hooks/a.py", [10, 11], [8])],
            snippets=[
                Snippet(
                    file_path="airflow/hooks/a.py",
                    line_number=10,
                    change_kind="added",
                    body=">>>     10 | x = 1",
                )
            ],
            is_new_file=False,
            is_deleted_file=False,
        )
        comment = core.format_comment([rule_diff])
        self.assertIn("## Ruling Diff Summary", comment)
        self.assertIn("<details>", comment)
        self.assertIn("**Added** `airflow/hooks/a.py` (line 10)", comment)
        self.assertIn(">>>     10 | x = 1", comment)
        self.assertIn("```python", comment)

    def test_format_comment_multiple_rules(self) -> None:
        rule_diffs = [
            RuleDiff(
                project="airflow",
                repo="python",
                rule_key="S107",
                file_diffs=[IssueDiff("airflow/hooks/a.py", [10], [])],
                snippets=[
                    Snippet("airflow/hooks/a.py", 10, "added", ">>>     10 | return 1")
                ],
                is_new_file=False,
                is_deleted_file=False,
            ),
            RuleDiff(
                project="django",
                repo="python",
                rule_key="S3699",
                file_diffs=[IssueDiff("django/core/b.py", [20], [15])],
                snippets=[
                    Snippet(
                        "django/core/b.py", 15, "removed", ">>>     15 | return None"
                    )
                ],
                is_new_file=False,
                is_deleted_file=False,
            ),
        ]
        comment = core.format_comment(rule_diffs)
        self.assertIn("Detected changes in 2 rule files", comment)
        self.assertIn("S107", comment)
        self.assertIn("S3699", comment)

    def test_format_comment_respects_collapse(self) -> None:
        rule_diff = RuleDiff(
            project="airflow",
            repo="python",
            rule_key="S107",
            file_diffs=[IssueDiff("airflow/hooks/a.py", [10], [])],
            snippets=[
                Snippet("airflow/hooks/a.py", 10, "added", ">>>     10 | return 1")
            ],
            is_new_file=False,
            is_deleted_file=False,
        )
        comment = core.format_comment([rule_diff])
        self.assertIn("<details>", comment)
        self.assertIn("</details>", comment)

    def test_strip_project_key_from_path(self) -> None:
        self.assertEqual(
            core.strip_project_key("airflow:airflow/foo.py"), "airflow/foo.py"
        )

    def test_line_zero_displayed_as_file_level(self) -> None:
        rule_diff = RuleDiff(
            project="specific-rules",
            repo="python",
            rule_key="S1451",
            file_diffs=[IssueDiff("S1716.py", [0], [0])],
            snippets=[Snippet("S1716.py", 0, "added", ">>> FILE-LEVEL ISSUE")],
            is_new_file=False,
            is_deleted_file=False,
        )
        comment = core.format_comment([rule_diff])
        self.assertIn("file-level", comment)
        self.assertIn(">>> FILE-LEVEL ISSUE", comment)

    def test_format_comment_truncates_when_limit_reached(self) -> None:
        rule_diffs = [
            RuleDiff(
                project=f"project-{index}",
                repo="python",
                rule_key=f"S{1000 + index}",
                file_diffs=[IssueDiff("a.py", [1], [2])],
                snippets=[
                    Snippet(
                        "a.py", 1, "added", "\n".join([f"line {i}" for i in range(50)])
                    )
                ],
                is_new_file=False,
                is_deleted_file=False,
            )
            for index in range(5)
        ]
        comment = core.format_comment(rule_diffs, soft_limit=500)
        self.assertIn("diff too large to display fully", comment)


class SnippetRenderingTest(unittest.TestCase):
    def test_render_line_snippet_uses_plus_minus_five_lines(self) -> None:
        lines = [f"line {i}" for i in range(1, 21)]
        rendered = core.render_line_snippet(lines, issue_line=10, context=5)
        self.assertIn("      5 | line 5", rendered)
        self.assertIn(">>>     10 | line 10", rendered)
        self.assertIn("     15 | line 15", rendered)

    def test_render_line_snippet_handles_out_of_range_line(self) -> None:
        rendered = core.render_line_snippet(["alpha", "beta"], issue_line=99, context=5)
        self.assertIn("requested line 99 not present", rendered)
        self.assertIn(">>>      2 | beta", rendered)

    def test_render_file_level_snippet_marker(self) -> None:
        rendered = core.render_file_level_snippet(["a", "b", "c"], context=5)
        self.assertIn(">>> FILE-LEVEL ISSUE", rendered)

    def test_render_snippet_missing_source_placeholder(self) -> None:
        rendered = core.render_snippet(None, issue_line=12, context=5)
        self.assertEqual(rendered, "(source file not found in checkout)")


class BuildRuleDiffsWithIOTest(unittest.TestCase):
    @patch("ruling_diff_core_lib.snippet_generation.Path.read_text")
    def test_build_rule_diffs_compares_json_refs_and_reads_checkout(self, mocked_read) -> None:
        changed_file = (
            "its/ruling/src/test/resources/expected/"
            "airflow/python-S107.json"
        )
        io_impl = FakeRulingDiffIO(
            json_by_ref_path={
                (changed_file, "base-sha"): {"airflow:a.py": [2]},
                (changed_file, "head-sha"): {"airflow:a.py": [2, 7]},
            },
        )
        mocked_read.return_value = "\n".join(
            [f"line {index}" for index in range(1, 12)]
        )

        diffs = core.build_rule_diffs([changed_file], "base-sha", "head-sha", io_impl)

        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].project, "airflow")
        self.assertEqual(diffs[0].repo, "python")
        self.assertEqual(diffs[0].rule_key, "S107")
        self.assertEqual(diffs[0].file_diffs[0].added_lines, [7])
        self.assertEqual(diffs[0].file_diffs[0].removed_lines, [])
        self.assertIn((changed_file, "base-sha"), io_impl.load_json_calls)
        self.assertIn((changed_file, "head-sha"), io_impl.load_json_calls)
        self.assertEqual(io_impl.resolve_calls, [("airflow", "a.py")])
        self.assertIn(">>>      7 | line 7", diffs[0].snippets[0].body)
        mocked_read.assert_called_once_with(encoding="utf-8")

    @patch("ruling_diff_core_lib.snippet_generation.Path.read_text")
    def test_build_rule_diffs_caches_source_per_path_across_changes_and_rules(
        self, mocked_read
    ) -> None:
        ruling_root = "private/its/ruling/src/test/resources/expected/airflow"
        changed_file = f"{ruling_root}/python-S107.json"
        other_changed_file = f"{ruling_root}/python-S108.json"
        io_impl = FakeRulingDiffIO(
            json_by_ref_path={
                (changed_file, "base-sha"): {"airflow:a.py": [1]},
                (changed_file, "head-sha"): {"airflow:a.py": [2, 2]},
                (other_changed_file, "head-sha"): {"airflow:a.py": [3]},
            },
        )
        mocked_read.return_value = "checkout first\ncheckout second\ncheckout third\n"

        diffs = core.build_rule_diffs(
            [changed_file, other_changed_file], "base-sha", "head-sha", io_impl
        )

        snippets = [snippet for diff in diffs for snippet in diff.snippets]
        self.assertEqual(len(snippets), 3)
        self.assertEqual({snippet.change_kind for snippet in snippets}, {"added", "removed"})
        for snippet in snippets:
            self.assertIn("checkout", snippet.body)
        mocked_read.assert_called_once_with(encoding="utf-8")

    @patch(
        "ruling_diff_core_lib.snippet_generation.Path.read_text",
        side_effect=FileNotFoundError,
    )
    def test_build_rule_diffs_missing_source_produces_placeholder_snippet(
        self, mocked_read
    ) -> None:
        changed_file = (
            "private/its/ruling/src/test/resources/expected/"
            "airflow/python-S107.json"
        )
        io_impl = FakeRulingDiffIO(
            json_by_ref_path={
                (changed_file, "base-sha"): {"airflow:a.py": [1]},
                (changed_file, "head-sha"): {"airflow:a.py": [1, 3]},
            },
        )

        diffs = core.build_rule_diffs([changed_file], "base-sha", "head-sha", io_impl)

        self.assertEqual(len(diffs[0].snippets), 1)
        self.assertEqual(
            diffs[0].snippets[0].body,
            "(source file not found in checkout: a.py)",
        )
        mocked_read.assert_called_once_with(encoding="utf-8")


class SourceLoadingTest(unittest.TestCase):
    def test_reads_utf8_source_from_checkout_and_caches_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = pathlib.Path(tmp_dir) / "source.py"
            source.write_text("café\nsecond line\n", encoding="utf-8")
            cache = {}

            lines = load_source_lines_with_cache(cache, str(source), (tmp_dir,))
            source.unlink()

            self.assertEqual(lines, ["café", "second line"])
            self.assertIs(load_source_lines_with_cache(cache, str(source), (tmp_dir,)), lines)
            self.assertEqual(cache, {str(source): lines})

    def test_caches_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = pathlib.Path(tmp_dir) / "missing.py"
            cache = {}

            self.assertIsNone(load_source_lines_with_cache(cache, str(source), (tmp_dir,)))
            source.write_text("created after first lookup", encoding="utf-8")

            self.assertIsNone(load_source_lines_with_cache(cache, str(source), (tmp_dir,)))
            self.assertEqual(cache, {str(source): None})

    def test_distinguishes_empty_source_from_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = pathlib.Path(tmp_dir) / "empty.py"
            source.write_text("", encoding="utf-8")

            self.assertEqual(load_source_lines_with_cache({}, str(source), (tmp_dir,)), [])

    def test_caches_different_source_paths_independently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            first_source = pathlib.Path(tmp_dir) / "first.py"
            second_source = pathlib.Path(tmp_dir) / "second.py"
            first_source.write_text("first", encoding="utf-8")
            second_source.write_text("second", encoding="utf-8")
            cache = {}

            self.assertEqual(
                load_source_lines_with_cache(cache, str(first_source), (tmp_dir,)),
                ["first"],
            )
            self.assertEqual(
                load_source_lines_with_cache(cache, str(second_source), (tmp_dir,)),
                ["second"],
            )

    def test_project_sources_accepts_internal_source_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sources_root = pathlib.Path(tmp_dir) / "sources_ruling"
            internal_root = pathlib.Path(tmp_dir) / "sources_internal_ruling"
            sources_root.mkdir()
            internal_root.mkdir()
            source = internal_root / "source.py"
            source.write_text("internal source\n", encoding="utf-8")
            io_impl = FakeRulingDiffIO({}, sources_root=str(sources_root))

            with (
                patch.object(
                    snippet_generation,
                    "SOURCES_INTERNAL_RULING_ROOT",
                    str(internal_root),
                ),
                patch.object(io_impl, "resolve_source_path", return_value=str(source)),
            ):
                snippet = snippet_generation.create_issue_snippet(
                    project="project",
                    file_path="source.py",
                    line_number=1,
                    change_kind="added",
                    source_cache={},
                    io=io_impl,
                )

            self.assertIn("internal source", snippet.body)

    def test_rejects_paths_outside_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = pathlib.Path(tmp_dir) / "allowed"
            root.mkdir()
            outside = pathlib.Path(tmp_dir) / "secret.py"
            outside.write_text("secret", encoding="utf-8")
            source_path = root / ".." / "secret.py"
            cache = {}

            self.assertIsNone(
                load_source_lines_with_cache(cache, str(source_path), (str(root),))
            )
            self.assertEqual(cache, {str(source_path): None})

    def test_rejects_symlinks_outside_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = pathlib.Path(tmp_dir) / "allowed"
            root.mkdir()
            outside = pathlib.Path(tmp_dir) / "secret.py"
            outside.write_text("secret", encoding="utf-8")
            link = root / "source.py"
            link.symlink_to(outside)

            self.assertIsNone(
                load_source_lines_with_cache({}, str(link), (str(root),))
            )


class GitHubCommentLookupTest(unittest.TestCase):
    @patch("ruling_diff_io.run_command")
    def test_get_existing_comment_id_reads_all_pages(self, mocked_run_command) -> None:
        mocked_run_command.return_value = (
            '[{"id": 1, "body": "first"}]\n'
            '[{"id": 2, "body": "text <!-- ruling-diff-comment -->"}]\n'
        )

        comment_id = io.get_existing_comment_id(
            "895", "SonarSource/sonar-python-enterprise"
        )

        self.assertEqual(comment_id, "2")

    def test_parse_json_documents_handles_multiple_arrays(self) -> None:
        documents = io.parse_json_documents('[{"a":1}]\n[{"b":2}]')
        self.assertEqual(len(documents), 2)


class GitHubActionIOTest(unittest.TestCase):
    def test_resolve_source_path_for_project_rulings_uses_path_directly(self) -> None:
        io_impl = io.GitHubActionIO()
        self.assertEqual(
            io_impl.resolve_source_path("project", "biopython/Bio/Nexus/Nexus.py"),
            "private/its-enterprise/sources_ruling/biopython/Bio/Nexus/Nexus.py",
        )

    def test_resolve_source_path_for_project_rulings_falls_back_to_sources_internal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sources_ruling = f"{tmp_dir}/sources_ruling"
            sources_internal = f"{tmp_dir}/sources_internal_ruling"
            sources_namespace = f"{tmp_dir}/sources_internal_namespace_ruling"
            pathlib.Path(sources_ruling).mkdir(parents=True, exist_ok=True)
            pathlib.Path(sources_internal).mkdir(parents=True, exist_ok=True)
            pathlib.Path(sources_namespace).mkdir(parents=True, exist_ok=True)
            target = f"{sources_internal}/foo.py"
            pathlib.Path(target).write_text("x\n", encoding="utf-8")
            with (
                patch.object(io, "RULING_SOURCES_SUBMODULE", sources_ruling),
                patch.object(io, "SOURCES_INTERNAL_RULING_ROOT", sources_internal),
                patch.object(
                    io,
                    "SOURCES_INTERNAL_NAMESPACE_RULING_ROOT",
                    sources_namespace,
                ),
            ):
                io_impl = io.GitHubActionIO(sources_root=sources_ruling)
                self.assertEqual(io_impl.resolve_source_path("project", "foo.py"), target)

    def test_resolve_source_path_for_project_rulings_falls_back_to_namespace_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sources_ruling = f"{tmp_dir}/sources_ruling"
            sources_internal = f"{tmp_dir}/sources_internal_ruling"
            sources_namespace = f"{tmp_dir}/sources_internal_namespace_ruling"
            namespace_child = f"{sources_namespace}/basic_namespace"
            pathlib.Path(sources_ruling).mkdir(parents=True, exist_ok=True)
            pathlib.Path(sources_internal).mkdir(parents=True, exist_ok=True)
            pathlib.Path(namespace_child).mkdir(parents=True, exist_ok=True)
            target = f"{namespace_child}/foo.py"
            pathlib.Path(target).write_text("x\n", encoding="utf-8")
            with (
                patch.object(io, "RULING_SOURCES_SUBMODULE", sources_ruling),
                patch.object(io, "SOURCES_INTERNAL_RULING_ROOT", sources_internal),
                patch.object(
                    io,
                    "SOURCES_INTERNAL_NAMESPACE_RULING_ROOT",
                    sources_namespace,
                ),
            ):
                io_impl = io.GitHubActionIO(sources_root=sources_ruling)
                self.assertEqual(io_impl.resolve_source_path("project", "foo.py"), target)

    def test_resolve_source_path_for_project_rulings_returns_primary_on_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sources_ruling = f"{tmp_dir}/sources_ruling"
            sources_internal = f"{tmp_dir}/sources_internal_ruling"
            sources_namespace = f"{tmp_dir}/sources_internal_namespace_ruling"
            pathlib.Path(sources_ruling).mkdir(parents=True, exist_ok=True)
            pathlib.Path(sources_internal).mkdir(parents=True, exist_ok=True)
            pathlib.Path(sources_namespace).mkdir(parents=True, exist_ok=True)
            primary = f"{sources_ruling}/missing.py"
            with (
                patch.object(io, "RULING_SOURCES_SUBMODULE", sources_ruling),
                patch.object(io, "SOURCES_INTERNAL_RULING_ROOT", sources_internal),
                patch.object(
                    io,
                    "SOURCES_INTERNAL_NAMESPACE_RULING_ROOT",
                    sources_namespace,
                ),
            ):
                io_impl = io.GitHubActionIO(sources_root=sources_ruling)
                self.assertEqual(io_impl.resolve_source_path("project", "missing.py"), primary)

    def test_resolve_source_path_uses_project_overrides(self) -> None:
        io_impl = io.GitHubActionIO()
        self.assertEqual(
            io_impl.resolve_source_path("mypy", "pkg/file.py"),
            "private/its-enterprise/sources_ruling/mypy-0.782/pkg/file.py",
        )

    def test_resolve_source_path_uses_default_project_root(self) -> None:
        io_impl = io.GitHubActionIO()
        self.assertEqual(
            io_impl.resolve_source_path("custom-project", "/pkg/file.py"),
            "private/its-enterprise/sources_ruling/custom-project/pkg/file.py",
        )


if __name__ == "__main__":
    unittest.main()
