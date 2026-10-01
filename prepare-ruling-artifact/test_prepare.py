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
        create_json: bool = True,
    ) -> tuple[subprocess.CompletedProcess[str], str | None, Path]:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        workspace = Path(self.directory.name)
        for root in roots:
            project = workspace / root / "project"
            project.mkdir(parents=True)
            if create_json:
                (project / "xml-S123.json").write_text('{"rule": [1]}')
        output = workspace / "github-output"
        result = subprocess.run(
            (sys.executable, str(SCRIPT)),
            cwd=workspace,
            env={
                **os.environ,
                "ARTIFACT_NAME": artifact_name,
                "RUNNER_TEMP": str(workspace),
                "GITHUB_OUTPUT": str(output),
            },
            capture_output=True,
            text=True,
        )
        stage_path = output.read_text().removeprefix("path=").strip() if output.exists() else None
        return result, stage_path, workspace

    def test_stages_public_ruling_results(self) -> None:
        result, stage_path, _ = self.run_preparer(("its/ruling/target/actual",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (Path(stage_path) / "expected/project/xml-S123.json").read_text(),
            '{"rule": [1]}',
        )

    def test_stages_private_ruling_results(self) -> None:
        result, stage_path, _ = self.run_preparer(("private/its/ruling/target/actual",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((Path(stage_path) / "expected/project/xml-S123.json").exists())

    def test_stages_gradle_ruling_results(self) -> None:
        for root in (
            "its/ruling/build/actual",
            "private/its/ruling/build/actual",
            "build/actual",
        ):
            with self.subTest(root=root):
                result, stage_path, _ = self.run_preparer((root,))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((Path(stage_path) / "expected/project/xml-S123.json").exists())

    def test_rejects_missing_and_ambiguous_layouts(self) -> None:
        missing, _, _ = self.run_preparer(())
        ambiguous, _, _ = self.run_preparer(
            ("its/ruling/target/actual", "private/its/ruling/target/actual")
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("No generated ruling directory", missing.stderr)
        self.assertIn("its/ruling/target/actual", missing.stderr)
        self.assertIn("private/its/ruling/build/actual", missing.stderr)
        self.assertIn("build/actual", missing.stderr)
        self.assertNotEqual(ambiguous.returncode, 0)
        self.assertIn("Multiple generated ruling directories", ambiguous.stderr)
        self.assertIn("its/ruling/target/actual", ambiguous.stderr)
        self.assertIn("private/its/ruling/target/actual", ambiguous.stderr)

    def test_rejects_nonstandard_directory(self) -> None:
        result, _, _ = self.run_preparer(("custom/actual",))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No generated ruling directory", result.stderr)
        self.assertIn("its/ruling/target/actual", result.stderr)

    def test_rejects_directory_without_json(self) -> None:
        result, stage_path, _ = self.run_preparer(
            ("its/ruling/target/actual",), create_json=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(stage_path)
        self.assertIn("No generated ruling JSON files", result.stderr)

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
