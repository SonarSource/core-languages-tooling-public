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
from ruling_diff_core_lib.models_and_constants import SarifReport


IssueLocation = core.IssueLocation
IssueDiff = core.IssueDiff
RuleDiff = core.RuleDiff
Snippet = core.Snippet


class FakeRulingDiffIO:
    def __init__(
        self,
        reports_by_ref_path: dict[tuple[str, str], SarifReport | None],
        text_by_ref_path: dict[tuple[str, str], str | None],
        ruling_root: str | None = None,
        sources_root: str = "private/its-enterprise/sources_ruling",
    ) -> None:
        self.sarif_by_ref_path = reports_by_ref_path
        self.text_by_ref_path = text_by_ref_path
        self.ruling_root = ruling_root
        self.sources_root = sources_root
        self.load_sarif_calls: list[tuple[str, str]] = []
        self.load_text_calls: list[tuple[str, str]] = []
        self.resolve_calls: list[tuple[str, str]] = []

    def load_sarif_at_ref(self, path: str, ref: str) -> SarifReport | None:
        self.load_sarif_calls.append((path, ref))
        return self.sarif_by_ref_path.get((path, ref))

    def load_text_at_ref(self, path: str, ref: str) -> str | None:
        self.load_text_calls.append((path, ref))
        return self.text_by_ref_path.get((path, ref))

    def resolve_source_path(self, project: str, file_path: str) -> str:
        self.resolve_calls.append((project, file_path))
        return f"sources/{project}/{file_path.lstrip('/')}"


class ChangedRulingFilesTest(unittest.TestCase):
    def test_discovers_all_expected_roots(self) -> None:
        standard = "its/ruling/src/test/resources/expected/alpha/java-S100.sarif"
        enterprise = "private/its/ruling/src/test/resources/expected/beta/java-S200.sarif"
        python_enterprise = "private/its-enterprise/ruling/src/test/resources/expected/gamma/python-S100.sarif"
        maven_actual = "its/ruling/target/actual/alpha/java-S300.sarif"
        gradle_actual = "private/its/ruling/build/actual/beta/java-S300.sarif"
        obsolete = (
            "private/its-enterprise/ruling/src/test/resources/expected_ruling/"
            "alpha/java-S400.sarif"
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

    def test_only_sarif_reports_are_discovered(self) -> None:
        root = "its/ruling/src/test/resources/expected/alpha/"
        paths = [root + name for name in (
            "java-S100.sarif", "java-S100.json", "java-S100.sarif.json", "java-S100.txt",
        )]
        with patch.object(io, "run_command", return_value="\n".join(paths)):
            self.assertEqual(io.get_changed_ruling_files("base", "head"), [paths[0]])

    def test_explicit_root_restricts_discovery(self) -> None:
        root = "custom/expected"
        with patch.object(
            io, "run_command", return_value=f"{root}/alpha/java-S100.sarif"
        ) as run_command:
            changed = io.get_changed_ruling_files("base", "head", root)

        self.assertEqual(changed, [f"{root}/alpha/java-S100.sarif"])
        run_command.assert_called_once_with(
            ["git", "diff", "--name-only", "base...head", "--", f"{root}/"]
        )


class ParsePathTest(unittest.TestCase):
    def test_parse_standard_ruling_path(self) -> None:
        path = "its/ruling/src/test/resources/expected/airflow/python-S1066.sarif"
        self.assertEqual(core.parse_ruling_path(path), ("airflow", "python", "S1066"))

    def test_rejects_generated_actual_path(self) -> None:
        with self.assertRaises(ValueError):
            core.parse_ruling_path("its/ruling/target/actual/airflow/python-S1066.sarif")

    def test_parse_ruling_path(self) -> None:
        path = "private/its/ruling/src/test/resources/expected/airflow/python-S1066.sarif"
        self.assertEqual(core.parse_ruling_path(path), ("airflow", "python", "S1066"))

    def test_parse_python_enterprise_layout(self) -> None:
        for repository in ("python", "pythonenterprise"):
            with self.subTest(repository=repository):
                path = (
                    "private/its-enterprise/ruling/src/test/resources/expected/"
                    f"specific-rules/{repository}-S7471.sarif"
                )
                self.assertEqual(core.parse_ruling_path(path), ("specific-rules", repository, "S7471"))

    def test_parse_ruling_path_with_pythonenterprise(self) -> None:
        path = "private/its/ruling/src/test/resources/expected/specific-rules/pythonenterprise-S7471.sarif"
        self.assertEqual(
            core.parse_ruling_path(path),
            ("specific-rules", "pythonenterprise", "S7471"),
        )

    def test_parse_ruling_path_with_legacy_key(self) -> None:
        path = "private/its/ruling/src/test/resources/expected/scikit-learn/python-LineLength.sarif"
        self.assertEqual(
            core.parse_ruling_path(path),
            ("scikit-learn", "python", "LineLength"),
        )

    def test_parse_rule_filename_rejects_empty_rule_key(self) -> None:
        with self.assertRaises(ValueError):
            core.parse_rule_filename("python-.sarif")

    def test_parse_rule_filename_rejects_empty_repository(self) -> None:
        with self.assertRaises(ValueError):
            core.parse_rule_filename("-S1066.sarif")

    def test_rejects_non_sarif_filenames(self) -> None:
        for filename in ("java-S100.json", "java-S100.sarif.json", "java-S100.xml"):
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(ValueError, "Expected a .sarif report filename"):
                    core.parse_rule_filename(filename)

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


class DiffLogicTest(unittest.TestCase):
    def test_diff_sarif_reports_added_issues(self) -> None:
        diffs = core.diff_sarif_reports({"proj:a.py": [IssueLocation(1), IssueLocation(2)]}, {"proj:a.py": [IssueLocation(1), IssueLocation(2), IssueLocation(3)]})
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].file_path, "a.py")
        self.assertEqual(diffs[0].added_locations, [IssueLocation(3)])

    def test_diff_sarif_reports_removed_issues(self) -> None:
        diffs = core.diff_sarif_reports({"proj:a.py": [IssueLocation(1), IssueLocation(2), IssueLocation(3)]}, {"proj:a.py": [IssueLocation(1)]})
        self.assertEqual(diffs[0].removed_locations, [IssueLocation(2), IssueLocation(3)])

    def test_diff_sarif_reports_new_file_entry(self) -> None:
        diffs = core.diff_sarif_reports(
            {"proj:a.py": [IssueLocation(1)]},
            {"proj:a.py": [IssueLocation(1)], "proj:b.py": [IssueLocation(5)]},
        )
        self.assertEqual(diffs[0].file_path, "b.py")
        self.assertEqual(diffs[0].added_locations, [IssueLocation(5)])

    def test_diff_sarif_reports_removed_file_entry(self) -> None:
        diffs = core.diff_sarif_reports(
            {"proj:a.py": [IssueLocation(1)], "proj:b.py": [IssueLocation(5)]},
            {"proj:a.py": [IssueLocation(1)]},
        )
        self.assertEqual(diffs[0].file_path, "b.py")
        self.assertEqual(diffs[0].removed_locations, [IssueLocation(5)])

    def test_diff_sarif_reports_new_ruling_file(self) -> None:
        diffs = core.diff_sarif_reports(None, {"proj:a.py": [IssueLocation(10)]})
        self.assertEqual(diffs[0].added_locations, [IssueLocation(10)])

    def test_diff_sarif_reports_deleted_ruling_file(self) -> None:
        diffs = core.diff_sarif_reports({"proj:a.py": [IssueLocation(10)]}, None)
        self.assertEqual(diffs[0].removed_locations, [IssueLocation(10)])

    def test_diff_sarif_reports_no_changes(self) -> None:
        self.assertEqual(
            core.diff_sarif_reports(
                {"proj:a.py": [IssueLocation(10)], "proj:b.py": [IssueLocation(11), IssueLocation(12)]},
                {"proj:a.py": [IssueLocation(10)], "proj:b.py": [IssueLocation(11), IssueLocation(12)]},
            ),
            [],
        )

    def test_duplicate_locations_ignored(self) -> None:
        diffs = core.diff_sarif_reports({"proj:a.py": [IssueLocation(297)]}, {"proj:a.py": [IssueLocation(297), IssueLocation(297)]})
        self.assertEqual(diffs, [])


class FormattingTest(unittest.TestCase):
    def test_format_comment_single_rule(self) -> None:
        rule_diff = RuleDiff(
            project="airflow",
            repo="python",
            rule_key="S107",
            file_diffs=[IssueDiff("airflow/hooks/a.py", [IssueLocation(10), IssueLocation(11)], [IssueLocation(8)])],
            snippets=[
                Snippet(
                    file_path="airflow/hooks/a.py",
                    location=IssueLocation(10),
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
                file_diffs=[IssueDiff("airflow/hooks/a.py", [IssueLocation(10)], [])],
                snippets=[
                    Snippet("airflow/hooks/a.py", IssueLocation(10), "added", ">>>     10 | return 1")
                ],
                is_new_file=False,
                is_deleted_file=False,
            ),
            RuleDiff(
                project="django",
                repo="python",
                rule_key="S3699",
                file_diffs=[IssueDiff("django/core/b.py", [IssueLocation(20)], [IssueLocation(15)])],
                snippets=[
                    Snippet(
                        "django/core/b.py", IssueLocation(15), "removed", ">>>     15 | return None"
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
            file_diffs=[IssueDiff("airflow/hooks/a.py", [IssueLocation(10)], [])],
            snippets=[
                Snippet("airflow/hooks/a.py", IssueLocation(10), "added", ">>>     10 | return 1")
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
            file_diffs=[IssueDiff("S1716.py", [IssueLocation(0)], [IssueLocation(0)])],
            snippets=[Snippet("S1716.py", IssueLocation(0), "added", ">>> FILE-LEVEL ISSUE")],
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
                file_diffs=[IssueDiff("a.py", [IssueLocation(1)], [IssueLocation(2)])],
                snippets=[
                    Snippet(
                        "a.py", IssueLocation(1), "added", "\n".join([f"line {i}" for i in range(50)])
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
        self.assertEqual(rendered, "(source file not found at this revision)")


class BuildRuleDiffsWithIOTest(unittest.TestCase):
    def test_build_rule_diffs_uses_io_object_and_respects_refs(self) -> None:
        changed_file = (
            "its/ruling/src/test/resources/expected/"
            "airflow/python-S107.sarif"
        )
        io_impl = FakeRulingDiffIO(
            reports_by_ref_path={
                (changed_file, "base-sha"): {"airflow:a.py": [IssueLocation(2)]},
                (changed_file, "head-sha"): {"airflow:a.py": [IssueLocation(2), IssueLocation(7)]},
            },
            text_by_ref_path={
                ("sources/airflow/a.py", "head-sha"): "\n".join(
                    [f"line {index}" for index in range(1, 12)]
                ),
            },
        )

        diffs = core.build_rule_diffs([changed_file], "base-sha", "head-sha", io_impl)

        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].project, "airflow")
        self.assertEqual(diffs[0].repo, "python")
        self.assertEqual(diffs[0].rule_key, "S107")
        self.assertEqual(diffs[0].file_diffs[0].added_locations, [IssueLocation(7)])
        self.assertEqual(diffs[0].file_diffs[0].removed_locations, [])
        self.assertIn((changed_file, "base-sha"), io_impl.load_sarif_calls)
        self.assertIn((changed_file, "head-sha"), io_impl.load_sarif_calls)
        self.assertEqual(io_impl.resolve_calls, [("airflow", "a.py")])
        self.assertEqual(io_impl.load_text_calls, [("sources/airflow/a.py", "head-sha")])

    def test_build_rule_diffs_caches_source_loads_per_ref_and_path(self) -> None:
        changed_file = (
            "private/its/ruling/src/test/resources/expected/"
            "airflow/python-S107.sarif"
        )
        io_impl = FakeRulingDiffIO(
            reports_by_ref_path={
                (changed_file, "base-sha"): {"airflow:a.py": [IssueLocation(1)]},
                (changed_file, "head-sha"): {"airflow:a.py": [IssueLocation(2), IssueLocation(2)]},
            },
            text_by_ref_path={
                ("sources/airflow/a.py", "base-sha"): "base\ncontent\n",
                ("sources/airflow/a.py", "head-sha"): "head\ncontent\n",
            },
        )

        core.build_rule_diffs([changed_file], "base-sha", "head-sha", io_impl)

        self.assertEqual(io_impl.load_text_calls.count(("sources/airflow/a.py", "base-sha")), 1)
        self.assertEqual(io_impl.load_text_calls.count(("sources/airflow/a.py", "head-sha")), 1)

    def test_build_rule_diffs_missing_source_produces_placeholder_snippet(self) -> None:
        changed_file = (
            "private/its/ruling/src/test/resources/expected/"
            "airflow/python-S107.sarif"
        )
        io_impl = FakeRulingDiffIO(
            reports_by_ref_path={
                (changed_file, "base-sha"): {"airflow:a.py": [IssueLocation(1)]},
                (changed_file, "head-sha"): {"airflow:a.py": [IssueLocation(1), IssueLocation(3)]},
            },
            text_by_ref_path={("sources/airflow/a.py", "head-sha"): None},
        )

        diffs = core.build_rule_diffs([changed_file], "base-sha", "head-sha", io_impl)

        self.assertEqual(len(diffs[0].snippets), 1)
        self.assertEqual(
            diffs[0].snippets[0].body,
            "(source file not found at this revision: a.py)",
        )


class SourceLoadingTest(unittest.TestCase):
    @patch("ruling_diff_io.subprocess.run")
    def test_load_text_at_ref_reads_from_submodule_commit(self, mocked_run) -> None:
        mocked_run.side_effect = [
            subprocess.CompletedProcess(
                args=["git", "rev-parse"],
                returncode=0,
                stdout="subsha123\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "-C", "sources", "show"],
                returncode=0,
                stdout="print('from submodule')\n",
                stderr="",
            ),
        ]

        content = io.load_text_at_ref(
            "private/its-enterprise/sources_ruling/project/foo.py", "deadbeef"
        )

        self.assertEqual(content, "print('from submodule')\n")
    @patch("ruling_diff_io.subprocess.run")
    def test_load_text_at_ref_warns_when_source_missing(self, mocked_run) -> None:
        mocked_run.return_value = subprocess.CompletedProcess(
            args=["git"],
            returncode=128,
            stdout="",
            stderr="fatal: path 'missing.py' exists on disk, but not in 'deadbeef'",
        )
        with self.assertLogs(level="WARNING") as logs:
            content = io.load_text_at_ref("missing.py", "deadbeef")
        self.assertIsNone(content)
        self.assertTrue(any("not found at deadbeef" in log for log in logs.output))


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
