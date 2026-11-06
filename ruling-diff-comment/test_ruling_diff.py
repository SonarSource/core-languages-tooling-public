import json
import os
import pathlib
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
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
import ruling_diff as cli
from ruling_diff_core_lib.models_and_constants import SarifReport
from ruling_diff_core_lib.snippet_generation import load_source_lines_with_cache


IssueLocation = core.IssueLocation
IssueDiff = core.IssueDiff
RuleDiff = core.RuleDiff
Snippet = core.Snippet


class LocalCLITests(unittest.TestCase):
    CLI_DIRECTORY = Path(__file__).resolve().parent

    def git(self, repository: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.test",
             "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *arguments],
            cwd=repository, check=True, capture_output=True, text=True,
        ).stdout.strip()

    def run_cli(self, repository: Path, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.CLI_DIRECTORY), "--dry-run",
             "--base-sha", "HEAD~1", "--head-sha", "HEAD",
             "--sources-root", "its/sources", *arguments],
            cwd=repository, capture_output=True, text=True,
        )

    def write_ruling(self, path: Path, lines: list[int]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".sarif":
            data = {"version": "2.1.0", "runs": [{"results": [
                {"ruleId": "python:S100", "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": "sample:file.py"},
                    "region": {"startLine": line},
                }}]} for line in lines
            ]}]}
        else:
            data = {"sample:file.py": lines}
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_directory_cli_compares_sarif_and_ignores_legacy_json(self) -> None:
        for root in (
            "its/ruling/src/test/resources/expected",
            "private/its/ruling/src/test/resources/expected",
            "private/its-enterprise/ruling/src/test/resources/expected",
            "custom/expected",
        ):
            for extension in ("json", "sarif"):
                for change in ("modified", "added", "deleted", "unchanged"):
                    with self.subTest(root=root, extension=extension, change=change):
                        with tempfile.TemporaryDirectory() as directory:
                            repository = Path(directory)
                            self.git(repository, "init")
                            source = repository / "its/sources/sample/file.py"
                            source.parent.mkdir(parents=True)
                            source.write_text("first = 1\nsecond = 2\n", encoding="utf-8")
                            expected = repository / root / f"sample/python-S100.{extension}"
                            if change != "added":
                                self.write_ruling(expected, [1])
                            self.git(repository, "add", ".")
                            self.git(repository, "commit", "-m", "Base ruling")
                            if change == "deleted":
                                expected.unlink()
                            elif change != "unchanged":
                                self.write_ruling(expected, [1, 2])
                            self.git(repository, "add", ".")
                            self.git(repository, "commit", "--allow-empty", "-m", "Updated ruling")
                            original_head = self.git(repository, "rev-parse", "HEAD")
                            arguments = ["--ruling-root", root] if root == "custom/expected" else []

                            result = self.run_cli(repository, *arguments)

                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(self.git(repository, "status", "--porcelain"), "")
                            self.assertEqual(self.git(repository, "rev-parse", "HEAD"), original_head)
                            if extension == "json" or change == "unchanged":
                                self.assertEqual(result.stdout, "")
                                continue
                            self.assertTrue(result.stdout.startswith("<!-- ruling-diff-comment -->"))
                            self.assertIn("## Ruling Diff Summary", result.stdout)
                            self.assertIn("<b>S100</b> (<code>python</code>)", result.stdout)
                            if change == "deleted":
                                self.assertIn("1 issues removed, 0 issues added", result.stdout)
                                self.assertIn("first = 1", result.stdout)
                            else:
                                added = 2 if change == "added" else 1
                                self.assertIn(f"0 issues removed, {added} issues added", result.stdout)
                                self.assertIn("second = 2", result.stdout)

    def test_invalid_revision_exits_nonzero_without_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            self.git(repository, "init")
            result = self.run_cli(repository)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("Failed to generate ruling diff comment", result.stderr)

    def test_malformed_sarif_fails_and_legacy_json_is_ignored(self) -> None:
        for extension in ("json", "sarif"):
            with self.subTest(extension=extension), tempfile.TemporaryDirectory() as directory:
                repository = Path(directory)
                self.git(repository, "init")
                expected = repository / f"its/ruling/src/test/resources/expected/sample/python-S100.{extension}"
                self.write_ruling(expected, [1])
                self.git(repository, "add", ".")
                self.git(repository, "commit", "-m", "Base ruling")
                expected.write_text('{"invalid":', encoding="utf-8")
                self.git(repository, "add", ".")
                self.git(repository, "commit", "-m", "Malformed ruling")

                result = self.run_cli(repository)

                if extension == "json":
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("No changed ruling report files", result.stderr)
                    continue
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn(f"python-S100.{extension} at HEAD", result.stderr)
                self.assertIn("Malformed JSON", result.stderr)


class RulingDiffCLITest(unittest.TestCase):
    def setUp(self) -> None:
        environment = patch.dict(cli.os.environ, {"DSPY_MODEL": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def parse_args(self, *arguments: str):
        with patch.object(sys, "argv", ["ruling_diff.py", *arguments]):
            return cli.parse_args()

    def test_dry_run_does_not_require_github_context(self) -> None:
        args = self.parse_args("--dry-run", "--base-sha", "base", "--head-sha", "head")

        self.assertTrue(args.dry_run)
        self.assertTrue(cli.has_required_context(args))
        self.assertIsNone(args.pr_number)
        self.assertIsNone(args.repository)

    def test_output_file_does_not_require_github_context(self) -> None:
        args = cli.parse_args([
            "--output-file", "comment.md", "--base-sha", "base", "--head-sha", "head",
        ])
        self.assertTrue(cli.has_required_context(args))
        self.assertIsNone(args.repository)

    def test_empty_repository_is_valid_in_preview_modes(self) -> None:
        for preview in (["--dry-run"], ["--output-file", "comment.md"]):
            with self.subTest(preview=preview):
                args = cli.parse_args([
                    *preview, "--base-sha", "base", "--head-sha", "head",
                    "--repository", "",
                ])
                self.assertTrue(cli.has_required_context(args))

    def test_preview_modes_are_exclusive(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            cli.parse_args([
                "--dry-run", "--output-file", "comment.md",
                "--base-sha", "base", "--head-sha", "head",
            ])

    def test_posting_requires_github_context(self) -> None:
        for context in ([], ["--pr-number", "123"], ["--repository", "org/repo"]):
            with self.subTest(context=context), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as error:
                    self.parse_args("--base-sha", "base", "--head-sha", "head", *context)
                self.assertEqual(error.exception.code, 2)

    def test_dry_run_still_requires_revisions(self) -> None:
        for revisions in ([], ["--base-sha", "base"], ["--head-sha", "head"]):
            with self.subTest(revisions=revisions), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as error:
                    self.parse_args("--dry-run", *revisions)
                self.assertEqual(error.exception.code, 2)

    def test_dry_run_and_posting_use_same_comment(self) -> None:
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                arguments = ["--base-sha", "base", "--head-sha", "head"]
                arguments.extend(
                    ["--dry-run"] if dry_run
                    else ["--pr-number", "123", "--repository", "org/repo"]
                )
                args = self.parse_args(*arguments)
                output = StringIO()
                with (
                    patch.object(cli, "parse_args", return_value=args),
                    patch.object(cli, "get_changed_ruling_files", return_value=["ruling.json"]),
                    patch.object(cli, "GitHubActionIO") as io_factory,
                    patch.object(cli, "build_rule_diffs", return_value=["diff"]) as build,
                    patch.object(cli, "format_comment", return_value="markdown") as render,
                    patch.object(cli, "add_enhancer_review", return_value="enhanced markdown") as enhance,
                    patch.object(cli, "post_or_update_comment") as post,
                    redirect_stdout(output),
                ):
                    cli.main()

                build.assert_called_once_with(["ruling.json"], "base", "head", io_factory.return_value)
                render.assert_called_once_with(["diff"])
                enhance.assert_called_once_with("markdown", ["diff"])
                if dry_run:
                    self.assertEqual(output.getvalue(), "enhanced markdown\n")
                    post.assert_not_called()
                else:
                    self.assertEqual(output.getvalue(), "")
                    post.assert_called_once_with("123", "org/repo", "enhanced markdown")

    def test_output_file_writes_generated_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_file = pathlib.Path(directory) / "comment.md"
            with (
                patch.object(cli, "generate_comment", return_value="enhanced markdown") as generate,
                patch.object(cli, "post_or_update_comment") as post,
            ):
                cli.main([
                    "--output-file", str(output_file), "--base-sha", "base",
                    "--head-sha", "head",
                ])
            self.assertEqual(output_file.read_text(encoding="utf-8"), "enhanced markdown")
            generate.assert_called_once_with("base", "head", None, io.RULING_SOURCES_SUBMODULE)
            post.assert_not_called()

    def test_output_file_accepts_tmp_when_tmpdir_differs(self) -> None:
        with (
            tempfile.TemporaryDirectory() as repository_directory,
            tempfile.TemporaryDirectory() as tmpdir,
            tempfile.TemporaryDirectory(dir="/tmp") as output_directory,
        ):
            repository = Path(repository_directory)
            LocalCLITests().git(repository, "init")
            LocalCLITests().git(repository, "commit", "--allow-empty", "-m", "Base")
            output_file = Path(output_directory) / "ruling-comment.md"
            result = subprocess.run(
                [sys.executable, str(LocalCLITests.CLI_DIRECTORY),
                 "--output-file", str(output_file),
                 "--base-sha", "HEAD", "--head-sha", "HEAD"],
                cwd=repository,
                env={**os.environ, "TMPDIR": tmpdir},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output_file.read_text(encoding="utf-8"), "")

    def test_disallowed_output_file_fails_before_generation(self) -> None:
        with (
            patch.object(cli, "generate_comment") as generate,
            patch.object(cli, "add_enhancer_review") as enhance,
        ):
            with self.assertRaisesRegex(ValueError, "--output-file must be inside"):
                cli.main([
                    "--output-file", "/etc/ruling-comment.md",
                    "--base-sha", "base", "--head-sha", "head",
                ])
        generate.assert_not_called()
        enhance.assert_not_called()

    def test_output_file_rejects_symlink_outside_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_file = Path(directory) / "ruling-comment.md"
            output_file.symlink_to("/etc/ruling-comment.md")
            with patch.object(cli, "generate_comment") as generate:
                with self.assertRaisesRegex(ValueError, "--output-file must be inside"):
                    cli.main([
                        "--output-file", str(output_file),
                        "--base-sha", "base", "--head-sha", "head",
                    ])
            generate.assert_not_called()

    def test_output_file_is_empty_without_issue_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_file = pathlib.Path(directory) / "comment.md"
            output_file.write_text("stale comment", encoding="utf-8")
            with patch.object(cli, "generate_comment", return_value=None):
                cli.main([
                    "--output-file", str(output_file), "--base-sha", "base",
                    "--head-sha", "head",
                ])
            self.assertEqual(output_file.read_text(encoding="utf-8"), "")

    def test_generate_comment_uses_supplied_paths(self) -> None:
        with (
            patch.object(cli, "get_changed_ruling_files", return_value=["ruling.sarif"]) as changed,
            patch.object(cli, "GitHubActionIO") as io_factory,
            patch.object(cli, "build_rule_diffs", return_value=["diff"]) as build,
            patch.object(cli, "format_comment", return_value="markdown") as render,
            patch.object(cli, "add_enhancer_review", return_value="enhanced markdown") as enhance,
        ):
            comment = cli.generate_comment("base", "head", "custom/expected", "its/sources")
        self.assertEqual(comment, "enhanced markdown")
        changed.assert_called_once_with("base", "head", "custom/expected")
        io_factory.assert_called_once_with("custom/expected", "its/sources")
        build.assert_called_once_with(["ruling.sarif"], "base", "head", io_factory.return_value)
        render.assert_called_once_with(["diff"])
        enhance.assert_called_once_with("markdown", ["diff"])

    def test_dry_run_without_deltas_prints_nothing(self) -> None:
        args = self.parse_args("--dry-run", "--base-sha", "base", "--head-sha", "head")
        for changed_files in ([], ["ruling.json"]):
            with self.subTest(changed_files=changed_files):
                output = StringIO()
                with (
                    patch.object(cli, "parse_args", return_value=args),
                    patch.object(cli, "get_changed_ruling_files", return_value=changed_files),
                    patch.object(cli, "build_rule_diffs", return_value=[]),
                    patch.object(cli, "post_or_update_comment") as post,
                    redirect_stdout(output),
                ):
                    cli.main()
                self.assertEqual(output.getvalue(), "")
                post.assert_not_called()

    def test_dry_run_with_local_git_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = pathlib.Path(directory)

            def git(*arguments: str) -> str:
                return subprocess.run(
                    ["git", "-c", "user.name=Test", "-c", "user.email=test@example.test",
                     "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *arguments],
                    cwd=repository, check=True, capture_output=True, text=True,
                ).stdout.strip()

            git("init")
            expected = repository / "its/ruling/src/test/resources/expected/sample/python-S100.sarif"
            expected.parent.mkdir(parents=True)
            expected.write_text('{"version":"2.1.0","runs":[{"results":[{"locations":[{"physicalLocation":{"artifactLocation":{"uri":"sample:file.py"},"region":{"startLine":1}}}]}]}]}', encoding="utf-8")
            source = repository / "its/sources/sample/file.py"
            source.parent.mkdir(parents=True)
            source.write_text("first = 1\nsecond = 2\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "Base ruling")
            base = git("rev-parse", "HEAD")
            expected.write_text('{"version":"2.1.0","runs":[{"results":[{"locations":[{"physicalLocation":{"artifactLocation":{"uri":"sample:file.py"},"region":{"startLine":1}}}]},{"locations":[{"physicalLocation":{"artifactLocation":{"uri":"sample:file.py"},"region":{"startLine":2}}}]}]}]}', encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "Updated ruling")

            result = subprocess.run(
                [sys.executable, str(MODULE_DIR.resolve() / "ruling_diff.py"),
                 "--dry-run", "--base-sha", base, "--head-sha", "HEAD",
                 "--sources-root", "its/sources"],
                cwd=repository, check=True, capture_output=True, text=True,
            )

        self.assertIn("## Ruling Diff Summary", result.stdout)
        self.assertIn("0 issues removed, 1 issues added", result.stdout)
        self.assertIn("second = 2", result.stdout)


class FakeRulingDiffIO:
    def __init__(
        self,
        reports_by_ref_path: dict[tuple[str, str], SarifReport | None],
        ruling_root: str | None = None,
        sources_root: str = "sources",
    ) -> None:
        self.sarif_by_ref_path = reports_by_ref_path
        self.ruling_root = ruling_root
        self.sources_root = sources_root
        self.load_sarif_calls: list[tuple[str, str]] = []
        self.resolve_calls: list[tuple[str, str]] = []

    def load_sarif_at_ref(self, path: str, ref: str) -> SarifReport | None:
        self.load_sarif_calls.append((path, ref))
        return self.sarif_by_ref_path.get((path, ref))

    def resolve_source_path(self, project: str, file_path: str) -> str:
        self.resolve_calls.append((project, file_path))
        return f"{self.sources_root}/{project}/{file_path.lstrip('/')}"


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
        with patch("ruling_diff_core_lib.comment_rendering.COMMENT_SOFT_LIMIT", 500):
            comment = core.format_comment(rule_diffs)
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
    @patch("ruling_diff_core_lib.snippet_generation.Path.read_text")
    def test_limits_added_and_removed_snippets_for_a_file(self, mocked_read) -> None:
        changed_file = "its/ruling/src/test/resources/expected/sample/python-S100.sarif"
        removed_locations = [IssueLocation(number) for number in range(1, 6)]
        added_locations = [IssueLocation(number) for number in range(6, 11)]
        io_impl = FakeRulingDiffIO({
            (changed_file, "base"): {"sample:file.py": removed_locations},
            (changed_file, "head"): {"sample:file.py": added_locations},
        })
        mocked_read.return_value = "\n".join(f"line {number}" for number in range(1, 11))

        diffs = core.build_rule_diffs([changed_file], "base", "head", io_impl)

        self.assertEqual(
            [(snippet.change_kind, snippet.location.start_line) for snippet in diffs[0].snippets],
            [("removed", number) for number in range(1, 4)]
            + [("added", number) for number in range(6, 9)],
        )

    @patch("ruling_diff_core_lib.snippet_generation.Path.read_text", return_value="source")
    def test_limits_snippets_for_a_rule(self, mocked_read) -> None:
        changed_file = "its/ruling/src/test/resources/expected/sample/python-S100.sarif"
        file_paths = [f"file{number:02}.py" for number in range(20)]
        io_impl = FakeRulingDiffIO({
            (changed_file, "base"): {},
            (changed_file, "head"): {f"sample:{path}": [IssueLocation(1)] for path in file_paths},
        })

        diffs = core.build_rule_diffs([changed_file], "base", "head", io_impl)

        self.assertEqual([snippet.file_path for snippet in diffs[0].snippets], file_paths[:15])

    @patch("ruling_diff_core_lib.snippet_generation.Path.read_text")
    def test_build_rule_diffs_compares_refs_and_reads_checkout(self, mocked_read) -> None:
        changed_file = (
            "its/ruling/src/test/resources/expected/"
            "airflow/python-S107.sarif"
        )
        io_impl = FakeRulingDiffIO(
            reports_by_ref_path={
                (changed_file, "base-sha"): {"airflow:a.py": [IssueLocation(2)]},
                (changed_file, "head-sha"): {"airflow:a.py": [IssueLocation(2), IssueLocation(7)]},
            },
        )
        mocked_read.return_value = "\n".join([f"line {index}" for index in range(1, 12)])

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
        self.assertIn(">>>      7 | line 7", diffs[0].snippets[0].body)
        mocked_read.assert_called_once_with(encoding="utf-8")

    @patch("ruling_diff_core_lib.snippet_generation.Path.read_text")
    def test_build_rule_diffs_caches_source_per_path(self, mocked_read) -> None:
        changed_file = (
            "private/its/ruling/src/test/resources/expected/"
            "airflow/python-S107.sarif"
        )
        other_changed_file = (
            "private/its/ruling/src/test/resources/expected/"
            "airflow/python-S108.sarif"
        )
        io_impl = FakeRulingDiffIO(
            reports_by_ref_path={
                (changed_file, "base-sha"): {"airflow:a.py": [IssueLocation(1)]},
                (changed_file, "head-sha"): {"airflow:a.py": [IssueLocation(2), IssueLocation(2)]},
                (other_changed_file, "head-sha"): {"airflow:a.py": [IssueLocation(3)]},
            },
        )
        mocked_read.return_value = "checkout first\ncheckout second\ncheckout third\n"

        diffs = core.build_rule_diffs(
            [changed_file, other_changed_file], "base-sha", "head-sha", io_impl
        )

        self.assertEqual(len([snippet for diff in diffs for snippet in diff.snippets]), 3)
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
            "airflow/python-S107.sarif"
        )
        io_impl = FakeRulingDiffIO(
            reports_by_ref_path={
                (changed_file, "base-sha"): {"airflow:a.py": [IssueLocation(1)]},
                (changed_file, "head-sha"): {"airflow:a.py": [IssueLocation(1), IssueLocation(3)]},
            },
        )

        diffs = core.build_rule_diffs([changed_file], "base-sha", "head-sha", io_impl)

        self.assertEqual(len(diffs[0].snippets), 1)
        self.assertEqual(
            diffs[0].snippets[0].body,
            "(source file not found in checkout: a.py)",
        )


class SourceLoadingTest(unittest.TestCase):
    def test_rejects_paths_outside_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = pathlib.Path(tmp_dir) / "allowed"
            root.mkdir()
            outside = pathlib.Path(tmp_dir) / "secret.py"
            outside.write_text("secret", encoding="utf-8")

            self.assertIsNone(
                load_source_lines_with_cache({}, str(root / ".." / "secret.py"), str(root))
            )

    def test_rejects_symlinks_outside_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = pathlib.Path(tmp_dir) / "allowed"
            root.mkdir()
            outside = pathlib.Path(tmp_dir) / "secret.py"
            outside.write_text("secret", encoding="utf-8")
            link = root / "source.py"
            link.symlink_to(outside)

            self.assertIsNone(load_source_lines_with_cache({}, str(link), str(root)))


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
        overrides = {
            "sources_internal_ruling": "private/its-enterprise/sources_internal_ruling",
            "namespace_basic": "private/its-enterprise/sources_internal_namespace_ruling/basic_namespace",
            "namespace_mixed": "private/its-enterprise/sources_internal_namespace_ruling/mixed_namespace",
        }
        for project, source_root in overrides.items():
            with self.subTest(project=project):
                self.assertEqual(
                    io_impl.resolve_source_path(project, "pkg/file.py"),
                    f"{source_root}/pkg/file.py",
                )

    def test_resolve_source_path_uses_default_project_root(self) -> None:
        io_impl = io.GitHubActionIO()
        self.assertEqual(
            io_impl.resolve_source_path("custom-project", "/pkg/file.py"),
            "private/its-enterprise/sources_ruling/custom-project/pkg/file.py",
        )


if __name__ == "__main__":
    unittest.main()
