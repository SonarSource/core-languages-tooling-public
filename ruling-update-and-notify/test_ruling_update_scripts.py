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
    def test_copies_merged_artifacts_and_removes_temporary_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            destination = root / "ruling"
            (artifacts / "expected/project").mkdir(parents=True)
            (destination / "expected/project").mkdir(parents=True)
            (artifacts / "expected/project" / "new.json").write_text("new")
            (destination / "expected/project" / "existing.json").write_text("existing")

            sync_ruling_artifacts.sync_artifacts(destination, artifacts, "success")

            self.assertEqual((destination / "expected/project" / "new.json").read_text(), "new")
            self.assertEqual((destination / "expected/project" / "existing.json").read_text(), "existing")
            self.assertFalse(artifacts.exists())

    def test_syncs_python_enterprise_results_with_or_without_expected_wrapper(self) -> None:
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                resources = Path("private/its-enterprise/ruling/src/test/resources")
                expected = root / resources / "expected"
                (expected / "project").mkdir(parents=True)
                (expected / "project/python-S100.json").write_text("old")
                (expected / "project/python-S200.json").write_text("unchanged")
                artifacts = root / "artifacts"
                artifact_root = artifacts / "expected" if wrapped else artifacts
                (artifact_root / "project").mkdir(parents=True)
                (artifact_root / "project/python-S100.json").write_text("new")
                (artifact_root / "project/python-S300.json").write_text("added")

                ruling_root, sources_root = find_ruling_directory.find_ruling_paths(root)
                self.assertEqual(ruling_root, resources)
                self.assertEqual(sources_root, Path("private/its-enterprise/sources_ruling"))
                sync_ruling_artifacts.sync_artifacts(root / ruling_root, artifacts, "success")

                self.assertEqual((expected / "project/python-S100.json").read_text(), "new")
                self.assertEqual((expected / "project/python-S200.json").read_text(), "unchanged")
                self.assertEqual((expected / "project/python-S300.json").read_text(), "added")
                self.assertFalse((root / resources / "project").exists())
                self.assertFalse((expected / "expected").exists())
                self.assertFalse(artifacts.exists())

    def test_failure_annotation_stays_inside_log_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(sync_ruling_artifacts.os.environ, {
                "RULING_ROOT": directory, "DOWNLOAD_OUTCOME": "failure",
            }), patch.object(sync_ruling_artifacts, "ARTIFACT_DIRECTORY", Path(directory) / "missing"):
                log = StringIO()
                with redirect_stdout(log):
                    self.assertEqual(sync_ruling_artifacts.main(), 1)
                lines = log.getvalue().splitlines()
                self.assertEqual(lines[0], "::group::Syncing ruling artifacts")
                self.assertTrue(any(line.startswith("::error::") for line in lines[1:-1]))
                self.assertEqual(lines[-1], "::endgroup::")

    def test_rejects_missing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "No artifacts were downloaded"):
                sync_ruling_artifacts.sync_artifacts(root, root / "missing", "success")
            with self.assertRaisesRegex(RuntimeError, "Failed to download artifacts"):
                sync_ruling_artifacts.sync_artifacts(root, root / "missing", "failure")


class FindRulingDirectoryTests(unittest.TestCase):
    def test_selects_public_or_private_expected_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / find_ruling_directory.PUBLIC_ROOT / "expected").mkdir(parents=True)
            self.assertEqual(find_ruling_directory.find_ruling_paths(root), (
                find_ruling_directory.PUBLIC_ROOT, Path("its/sources"),
            ))

            (root / find_ruling_directory.PUBLIC_ROOT / "expected").rmdir()
            (root / find_ruling_directory.PRIVATE_ROOT / "expected").mkdir(parents=True)
            self.assertEqual(find_ruling_directory.find_ruling_paths(root), (
                find_ruling_directory.PRIVATE_ROOT, Path("private/its/sources"),
            ))

    def test_reports_missing_and_ambiguous_expected_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public_expected = root / find_ruling_directory.PUBLIC_ROOT / "expected"
            private_expected = root / find_ruling_directory.PRIVATE_ROOT / "expected"
            with self.assertRaisesRegex(ValueError, "No expected ruling directory found") as missing:
                find_ruling_directory.find_ruling_paths(root)
            self.assertIn(str(find_ruling_directory.PUBLIC_ROOT / "expected"), str(missing.exception))
            self.assertIn(str(find_ruling_directory.PRIVATE_ROOT / "expected"), str(missing.exception))

            public_expected.mkdir(parents=True)
            private_expected.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "Multiple expected ruling directories exist") as ambiguous:
                find_ruling_directory.find_ruling_paths(root)
            self.assertIn(str(find_ruling_directory.PUBLIC_ROOT / "expected"), str(ambiguous.exception))
            self.assertIn(str(find_ruling_directory.PRIVATE_ROOT / "expected"), str(ambiguous.exception))

    def test_rejects_enterprise_layout_alongside_other_layouts(self) -> None:
        enterprise_expected = Path("private/its-enterprise/ruling/src/test/resources/expected")
        for other in (find_ruling_directory.PUBLIC_ROOT, find_ruling_directory.PRIVATE_ROOT):
            with self.subTest(other=other), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / enterprise_expected).mkdir(parents=True)
                (root / other / "expected").mkdir(parents=True)
                with self.assertRaisesRegex(ValueError, "Multiple expected ruling directories exist") as ambiguous:
                    find_ruling_directory.find_ruling_paths(root)
                self.assertIn(str(enterprise_expected), str(ambiguous.exception))
                self.assertIn(str(other / "expected"), str(ambiguous.exception))

    def test_main_publishes_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output"
            with (
                patch.dict(find_ruling_directory.os.environ, {"GITHUB_OUTPUT": str(output_path)}),
                patch.object(find_ruling_directory, "find_ruling_paths", return_value=(
                    find_ruling_directory.PUBLIC_ROOT, Path("its/sources"),
                )),
            ):
                self.assertEqual(find_ruling_directory.main(), 0)
            self.assertEqual(output_path.read_text(),
                "ruling-root=its/ruling/src/test/resources\nsources-root=its/sources\n")


if __name__ == "__main__":
    unittest.main()
