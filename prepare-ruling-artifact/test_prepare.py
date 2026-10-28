from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare.py")


class PrepareRulingArtifactTests(unittest.TestCase):
    def run_preparer(
        self,
        roots: tuple[str, ...],
        artifact_name: str = "actual_ruling",
        result_files: tuple[str, ...] = ("xml-S123.json",),
        symlink_results: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], Path | None, Path]:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        workspace = Path(self.directory.name)
        for root in roots:
            project = workspace / root / "project"
            project.mkdir(parents=True)
            for filename in result_files:
                result_path = project / filename
                result_path.parent.mkdir(parents=True, exist_ok=True)
                if symlink_results:
                    target = workspace / "linked-result"
                    target.write_text('{"rule": [1]}')
                    result_path.symlink_to(target)
                else:
                    result_path.write_text('{"rule": [1]}')
        output = workspace / "github-output"
        result = subprocess.run(
            (sys.executable, str(SCRIPT)),
            cwd=workspace,
            env={
                **os.environ,
                "ARTIFACT_NAME": artifact_name,
                "GITHUB_OUTPUT": str(output),
            },
            capture_output=True,
            text=True,
        )
        upload_path = (
            workspace / output.read_text().removeprefix("path=").strip()
            if output.exists() else None
        )
        return result, upload_path, workspace

    def test_uploads_public_ruling_results_directly(self) -> None:
        result, upload_path, workspace = self.run_preparer(("its/ruling/target/actual",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(upload_path, workspace / "its/ruling/target/actual")
        self.assertEqual((upload_path / "project/xml-S123.json").read_text(), '{"rule": [1]}')
        self.assertFalse((upload_path / "expected").exists())

    def test_uploads_private_ruling_results(self) -> None:
        result, upload_path, workspace = self.run_preparer(("private/its/ruling/target/actual",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(upload_path, workspace / "private/its/ruling/target/actual")
        self.assertTrue((upload_path / "project/xml-S123.json").exists())

    def test_uploads_python_enterprise_ruling_results(self) -> None:
        for build_directory in ("target", "build"):
            with self.subTest(build_directory=build_directory):
                root = f"private/its-enterprise/ruling/{build_directory}/actual"
                result, upload_path, workspace = self.run_preparer((root,))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(upload_path, workspace / root)
                self.assertEqual((upload_path / "project/xml-S123.json").read_text(), '{"rule": [1]}')

    def test_rejects_enterprise_results_alongside_other_layouts(self) -> None:
        result, _, _ = self.run_preparer((
            "private/its/ruling/target/actual",
            "private/its-enterprise/ruling/target/actual",
        ))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Multiple generated ruling directories", result.stderr)

    def test_uploads_gradle_ruling_results(self) -> None:
        for root in (
            "its/ruling/build/actual",
            "private/its/ruling/build/actual",
        ):
            with self.subTest(root=root):
                result, upload_path, workspace = self.run_preparer((root,))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(upload_path, workspace / root)

    def test_uploads_sarif_ruling_results_in_all_standard_layouts(self) -> None:
        for root in (
            "its/ruling/target/actual",
            "private/its/ruling/target/actual",
            "its/ruling/build/actual",
            "private/its/ruling/build/actual",
        ):
            with self.subTest(root=root):
                result, upload_path, workspace = self.run_preparer(
                    (root,), result_files=("nested/report.sarif",)
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(upload_path, workspace / root)
                self.assertEqual(
                    (upload_path / "project/nested/report.sarif").read_text(),
                    '{"rule": [1]}',
                )

    def test_uploads_mixed_json_and_sarif_results(self) -> None:
        filenames = ("xml-S123.json", "nested/report.sarif", "support.txt")
        result, upload_path, _ = self.run_preparer(
            ("its/ruling/target/actual",), result_files=filenames
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for filename in filenames:
            with self.subTest(filename=filename):
                self.assertEqual(
                    (upload_path / "project" / filename).read_text(),
                    '{"rule": [1]}',
                )

    def test_rejects_missing_and_ambiguous_layouts(self) -> None:
        missing, _, _ = self.run_preparer(())
        ambiguous, _, _ = self.run_preparer(
            ("its/ruling/target/actual", "private/its/ruling/target/actual")
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("No generated ruling directory", missing.stderr)
        self.assertIn("its/ruling/target/actual", missing.stderr)
        self.assertIn("private/its/ruling/build/actual", missing.stderr)
        self.assertNotEqual(ambiguous.returncode, 0)
        self.assertIn("Multiple generated ruling directories", ambiguous.stderr)
        self.assertIn("its/ruling/target/actual", ambiguous.stderr)
        self.assertIn("private/its/ruling/target/actual", ambiguous.stderr)

    def test_rejects_nonstandard_directory(self) -> None:
        result, _, _ = self.run_preparer(("custom/actual",))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No generated ruling directory", result.stderr)
        self.assertIn("its/ruling/target/actual", result.stderr)

    def test_rejects_repository_root_build_directory(self) -> None:
        result, _, _ = self.run_preparer(("build/actual",))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No generated ruling directory", result.stderr)

    def test_rejects_directory_without_json_or_sarif(self) -> None:
        for filenames in ((), ("report.txt",), ("report.json/note.txt", "report.sarif/note.txt")):
            with self.subTest(filenames=filenames):
                result, upload_path, _ = self.run_preparer(
                    ("its/ruling/target/actual",), result_files=filenames
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(upload_path)
                self.assertIn("No generated ruling JSON or SARIF files", result.stderr)

    def test_rejects_symlink_only_results(self) -> None:
        for filename in ("xml-S123.json", "report.sarif"):
            with self.subTest(filename=filename):
                result, upload_path, _ = self.run_preparer(
                    ("its/ruling/target/actual",),
                    result_files=(filename,),
                    symlink_results=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(upload_path)
                self.assertIn("No generated ruling JSON or SARIF files", result.stderr)

    def test_rejects_ambiguous_maven_and_gradle_results(self) -> None:
        result, _, _ = self.run_preparer(
            ("its/ruling/target/actual", "its/ruling/build/actual")
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Multiple generated ruling directories", result.stderr)

    def test_rejects_artifact_names_outside_consumer_pattern(self) -> None:
        result, _, _ = self.run_preparer(("its/ruling/target/actual",), artifact_name="ruling")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("artifact-name must begin with actual_", result.stderr)


if __name__ == "__main__":
    unittest.main()
