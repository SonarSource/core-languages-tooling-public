from __future__ import annotations

import tempfile
import unittest
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

    def test_rejects_missing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "No artifacts were downloaded"):
                sync_ruling_artifacts.sync_artifacts(root, root / "missing", "success")
            with self.assertRaisesRegex(RuntimeError, "Failed to download artifacts"):
                sync_ruling_artifacts.sync_artifacts(root, root / "missing", "failure")


class FixPullRequestTests(unittest.TestCase):
    @patch.object(create_fix_pr, "run")
    @patch.object(create_fix_pr, "has_staged_changes", return_value=True)
    @patch.object(create_fix_pr.subprocess, "run", return_value=SimpleNamespace(returncode=2))
    def test_new_branch_creates_a_pull_request(self, remote, staged, run) -> None:
        def command_output(*command: str, **kwargs) -> str:
            if command[:2] == ("git", "status"):
                return " M its/ruling/result.json"
            if command[:3] == ("gh", "pr", "create"):
                return "https://github.com/org/repo/pull/1"
            if command[:3] == ("git", "rev-parse", "HEAD"):
                return "a" * 40
            return ""

        with patch.object(create_fix_pr, "output", side_effect=command_output):
            url, sha = create_fix_pr.create_fix_pr("feature", "its/ruling", "")

        self.assertEqual(url, "https://github.com/org/repo/pull/1")
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
            url, sha = create_fix_pr.create_fix_pr("feature", "its/ruling", "")

        self.assertEqual(url, "https://github.com/org/repo/pull/1")
        self.assertEqual(sha, "b" * 40)
        self.assertFalse(any(call.args[:3] == ("gh", "pr", "create") for call in output.call_args_list))
        self.assertFalse(any(call.args[:2] == ("git", "push") for call in run.call_args_list))
        remote.assert_called_once()
        staged.assert_called_once()


if __name__ == "__main__":
    unittest.main()
