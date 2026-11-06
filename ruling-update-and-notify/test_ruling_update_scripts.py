from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import find_ruling_directory
import sync_ruling_artifacts


class SyncArtifactsTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.artifacts = self.root / "artifacts"
        self.resources = self.root / "its/ruling/src/test/resources"
        self.expected = self.resources / "expected"
        (self.expected / "project").mkdir(parents=True)
        (self.expected / "project" / "report.sarif").write_text("old")
        (self.expected / "unrelated").mkdir()
        (self.expected / "unrelated" / "report.sarif").write_text("unrelated")

    def write_artifact(self, relative_path: str, content: str = "new") -> None:
        path = self.artifacts / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_updates_matching_expectation_and_removes_temporary_directory(self) -> None:
        self.write_artifact("project/report.sarif", '{"runs": []}')

        sync_ruling_artifacts.sync_artifacts(self.expected, self.artifacts, "success")

        self.assertEqual((self.expected / "project" / "report.sarif").read_text(), '{"runs": []}')
        self.assertEqual((self.expected / "unrelated" / "report.sarif").read_text(), "unrelated")
        self.assertFalse((self.expected / "expected").exists())
        self.assertFalse(self.artifacts.exists())

    def test_merges_disjoint_artifacts_without_deleting_other_projects(self) -> None:
        # download-artifact keeps multiple artifacts isolated to avoid extraction races.
        self.write_artifact("actual_linux/project/report.sarif", "from linux job")
        self.write_artifact("actual_windows/windows-project/report.sarif", "from windows job")

        sync_ruling_artifacts.sync_artifacts(self.expected, self.artifacts, "success")

        self.assertEqual((self.expected / "project" / "report.sarif").read_text(), "from linux job")
        self.assertEqual(
            (self.expected / "windows-project" / "report.sarif").read_text(), "from windows job"
        )
        self.assertEqual((self.expected / "unrelated" / "report.sarif").read_text(), "unrelated")

    def test_isolated_artifacts_apply_in_name_order(self) -> None:
        self.write_artifact("actual_windows/project/report.sarif", "windows")
        self.write_artifact("actual_linux/project/report.sarif", "linux")

        sync_ruling_artifacts.sync_artifacts(self.expected, self.artifacts, "success")

        self.assertEqual((self.expected / "project/report.sarif").read_text(), "windows")

    def test_copies_only_result_files_into_expected_directory(self) -> None:
        self.write_artifact("project/report.sarif")
        self.write_artifact("project/notes.txt")
        self.write_artifact("pom.xml")
        outside = self.root / "outside.sarif"
        outside.write_text("outside")
        (self.artifacts / "project" / "linked.sarif").symlink_to(outside)
        (self.artifacts / "linked-project").symlink_to(self.root, target_is_directory=True)

        sync_ruling_artifacts.sync_artifacts(self.expected, self.artifacts, "success")

        self.assertEqual(
            sorted(str(path.relative_to(self.resources)) for path in self.resources.rglob("*")
                   if path.is_file()),
            ["expected/project/report.sarif", "expected/unrelated/report.sarif"],
        )

    def test_refuses_to_write_through_symlinked_expectation(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (self.expected / "linked").symlink_to(outside, target_is_directory=True)
        self.write_artifact("linked/report.sarif")

        with self.assertRaisesRegex(RuntimeError, "Refusing to write through a symlink"):
            sync_ruling_artifacts.sync_artifacts(self.expected, self.artifacts, "success")
        self.assertFalse((outside / "report.sarif").exists())

    def test_syncs_python_enterprise_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "private/its-enterprise/ruling/src/test/resources/expected"
            (expected / "project").mkdir(parents=True)
            (expected / "project/python-S100.sarif").write_text("old")
            (expected / "project/python-S200.sarif").write_text("unchanged")
            artifacts = root / "artifacts"
            (artifacts / "project").mkdir(parents=True)
            (artifacts / "project/python-S100.sarif").write_text("new")
            (artifacts / "project/python-S300.sarif").write_text("added")

            expected_root, sources_root = find_ruling_directory.find_ruling_paths(root)
            self.assertEqual(root / expected_root, expected)
            self.assertEqual(sources_root, Path("private/its-enterprise/sources_ruling"))
            sync_ruling_artifacts.sync_artifacts(root / expected_root, artifacts, "success")

            self.assertEqual((expected / "project/python-S100.sarif").read_text(), "new")
            self.assertEqual((expected / "project/python-S200.sarif").read_text(), "unchanged")
            self.assertEqual((expected / "project/python-S300.sarif").read_text(), "added")
            self.assertFalse((expected / "expected").exists())
            self.assertFalse(artifacts.exists())

    def test_failure_annotation_stays_inside_log_group(self) -> None:
        with patch.dict(sync_ruling_artifacts.os.environ, {
            "EXPECTED_ROOT": str(self.expected), "DOWNLOAD_OUTCOME": "failure",
            "ARTIFACT_DIRECTORY": str(self.root / "missing"),
        }):
            log = StringIO()
            with redirect_stdout(log):
                self.assertEqual(sync_ruling_artifacts.main(), 1)
            lines = log.getvalue().splitlines()
            self.assertEqual(lines[0], "::group::Syncing ruling artifacts")
            self.assertTrue(any(line.startswith("::error::") for line in lines[1:-1]))
            self.assertEqual(lines[-1], "::endgroup::")

    def test_existing_expectations_do_not_hide_missing_artifacts(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "No artifacts were downloaded"):
            sync_ruling_artifacts.sync_artifacts(self.expected, self.root / "missing", "success")
        with self.assertRaisesRegex(RuntimeError, "Failed to download artifacts"):
            sync_ruling_artifacts.sync_artifacts(self.expected, self.artifacts, "failure")
        self.artifacts.mkdir()
        with self.assertRaisesRegex(RuntimeError, "Artifact directory is empty"):
            sync_ruling_artifacts.sync_artifacts(self.expected, self.artifacts, "success")
        self.write_artifact("project/notes.txt")
        with self.assertRaisesRegex(RuntimeError, "no regular SARIF result files"):
            sync_ruling_artifacts.sync_artifacts(self.expected, self.artifacts, "success")

    def test_rejects_missing_expected_directory(self) -> None:
        self.write_artifact("project/report.sarif")
        with self.assertRaisesRegex(RuntimeError, "Expected ruling directory does not exist"):
            sync_ruling_artifacts.sync_artifacts(self.root / "missing", self.artifacts, "success")


class FindRulingDirectoryTests(unittest.TestCase):
    def test_selects_public_or_private_expected_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "its/ruling/src/test/resources/expected").mkdir(parents=True)
            self.assertEqual(find_ruling_directory.find_ruling_paths(root), (
                Path("its/ruling/src/test/resources/expected"), Path("its/sources"),
            ))

            (root / "its/ruling/src/test/resources/expected").rmdir()
            (root / "private/its/ruling/src/test/resources/expected").mkdir(parents=True)
            self.assertEqual(find_ruling_directory.find_ruling_paths(root), (
                Path("private/its/ruling/src/test/resources/expected"),
                Path("private/its/sources"),
            ))

    def test_reports_missing_and_ambiguous_expected_directories(self) -> None:
        public_expected = "its/ruling/src/test/resources/expected"
        private_expected = "private/its/ruling/src/test/resources/expected"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "its/ruling/src/test/resources").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "No expected ruling directory found") as missing:
                find_ruling_directory.find_ruling_paths(root)
            self.assertIn(public_expected, str(missing.exception))
            self.assertIn(private_expected, str(missing.exception))

            (root / public_expected).mkdir(parents=True)
            (root / private_expected).mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "Multiple expected ruling directories exist") as ambiguous:
                find_ruling_directory.find_ruling_paths(root)
            self.assertIn(public_expected, str(ambiguous.exception))
            self.assertIn(private_expected, str(ambiguous.exception))

    def test_rejects_enterprise_layout_alongside_other_layouts(self) -> None:
        enterprise_expected = find_ruling_directory.ENTERPRISE_EXPECTED_ROOT
        for other in (
            find_ruling_directory.PUBLIC_EXPECTED_ROOT,
            find_ruling_directory.PRIVATE_EXPECTED_ROOT,
        ):
            with self.subTest(other=other), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / enterprise_expected).mkdir(parents=True)
                (root / other).mkdir(parents=True)
                with self.assertRaisesRegex(ValueError, "Multiple expected ruling directories exist") as ambiguous:
                    find_ruling_directory.find_ruling_paths(root)
                self.assertIn(str(enterprise_expected), str(ambiguous.exception))
                self.assertIn(str(other), str(ambiguous.exception))

    def test_main_publishes_expected_and_sources_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output"
            with (
                patch.dict(find_ruling_directory.os.environ, {"GITHUB_OUTPUT": str(output_path)}),
                patch.object(find_ruling_directory, "find_ruling_paths", return_value=(
                    find_ruling_directory.PUBLIC_EXPECTED_ROOT,
                    find_ruling_directory.PUBLIC_SOURCES_ROOT,
                )),
            ):
                self.assertEqual(find_ruling_directory.main(), 0)
            self.assertEqual(output_path.read_text(),
                "expected-root=its/ruling/src/test/resources/expected\n"
                "sources-root=its/sources\n")


if __name__ == "__main__":
    unittest.main()
