from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import create_fix_pr
import sync_ruling_artifacts


class SyncArtifactsTests(unittest.TestCase):
    def test_copies_merged_artifacts_and_removes_temporary_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            destination = root / "ruling"
            (artifacts / "project").mkdir(parents=True)
            (destination / "project").mkdir(parents=True)
            (artifacts / "project" / "new.json").write_text("new")
            (destination / "project" / "existing.json").write_text("existing")

            sync_ruling_artifacts.sync_artifacts(destination, artifacts, "success")

            self.assertEqual((destination / "project" / "new.json").read_text(), "new")
            self.assertEqual((destination / "project" / "existing.json").read_text(), "existing")
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


class FixPullRequestTests(unittest.TestCase):
    @patch.object(create_fix_pr, "create_fix_pr", return_value=("https://example.test/1", "b" * 40, "a" * 40))
    def test_main_publishes_fix_base_and_head(self, create) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output"
            with patch.dict(create_fix_pr.os.environ, {
                "TARGET_REF": "feature", "RULING_ROOT": "its/ruling",
                "PR_NUMBER": "1", "GITHUB_OUTPUT": str(output_path),
            }):
                self.assertEqual(create_fix_pr.main(), 0)
            self.assertEqual(output_path.read_text(),
                f"fix-pr-url=https://example.test/1\nfix-base-sha={'b' * 40}\nfix-sha={'a' * 40}\n")
            create.assert_called_once_with("feature", "its/ruling", "1")

    @patch.object(create_fix_pr.subprocess, "run")
    def test_output_does_not_capture_stderr(self, process) -> None:
        process.return_value.stdout = "result\n"
        self.assertEqual(create_fix_pr.output("gh", "pr", "create"), "result")
        self.assertEqual(process.call_args.kwargs, {
            "check": True, "stdout": create_fix_pr.subprocess.PIPE, "text": True,
        })

    @patch.object(create_fix_pr, "run")
    @patch.object(create_fix_pr, "has_staged_changes", return_value=True)
    @patch.object(create_fix_pr.subprocess, "run", return_value=SimpleNamespace(returncode=2))
    def test_new_branch_creates_a_pull_request(self, remote, staged, run) -> None:
        head_shas = iter(("b" * 40, "a" * 40))

        def command_output(*command: str, **kwargs) -> str:
            if command[:2] == ("git", "status"):
                return " M its/ruling/result.json"
            if command[:3] == ("gh", "pr", "create"):
                return "https://github.com/org/repo/pull/1"
            if command[:3] == ("git", "rev-parse", "HEAD"):
                return next(head_shas)
            return ""

        with patch.object(create_fix_pr, "output", side_effect=command_output):
            url, base_sha, sha = create_fix_pr.create_fix_pr("feature", "its/ruling", "")

        self.assertEqual(url, "https://github.com/org/repo/pull/1")
        self.assertEqual(base_sha, "b" * 40)
        self.assertEqual(sha, "a" * 40)
        run.assert_any_call("git", "push", "origin", "fix/update-ruling-for-feature")
        remote.assert_called_once()
        staged.assert_called_once()

    @patch.object(create_fix_pr, "run")
    @patch.object(create_fix_pr, "has_staged_changes", return_value=False)
    @patch.object(create_fix_pr.subprocess, "run", return_value=SimpleNamespace(returncode=0))
    def test_existing_branch_reuses_its_pull_request(self, remote, staged, run) -> None:
        def command_output(*command: str, **kwargs) -> str:
            if command[:3] == ("gh", "pr", "list"):
                return "https://github.com/org/repo/pull/1"
            if command[:3] == ("git", "rev-parse", "HEAD"):
                return "b" * 40
            return ""

        with patch.object(create_fix_pr, "output", side_effect=command_output) as output:
            url, base_sha, sha = create_fix_pr.create_fix_pr("feature", "its/ruling", "")

        self.assertEqual(url, "https://github.com/org/repo/pull/1")
        self.assertEqual(base_sha, "b" * 40)
        self.assertEqual(sha, "b" * 40)
        self.assertFalse(any(call.args[:3] == ("gh", "pr", "create") for call in output.call_args_list))
        self.assertFalse(any(call.args[:2] == ("git", "push") for call in run.call_args_list))
        remote.assert_called_once()
        staged.assert_called_once()


if __name__ == "__main__":
    unittest.main()
