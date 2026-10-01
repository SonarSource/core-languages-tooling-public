from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cleanup_fix_pr
import create_fix_pr
import find_ruling_directory
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
    @patch.object(create_fix_pr, "transfer_ruling_changes")
    @patch.object(create_fix_pr.subprocess, "run", return_value=SimpleNamespace(returncode=2, stdout=""))
    def test_new_branch_creates_a_pull_request(self, remote, transfer, staged, run) -> None:
        head_shas = iter(("b" * 40, "a" * 40))

        def command_output(*command: str, **kwargs) -> str:
            if command[:3] == ("gh", "pr", "create"):
                return "https://github.com/org/repo/pull/1"
            if "rev-parse" in command:
                return next(head_shas)
            return ""

        with patch.object(create_fix_pr, "output", side_effect=command_output):
            url, base_sha, sha = create_fix_pr.create_fix_pr("feature", "its/ruling", "123")

        self.assertEqual(url, "https://github.com/org/repo/pull/1")
        self.assertEqual(base_sha, "b" * 40)
        self.assertEqual(sha, "a" * 40)
        self.assertTrue(any(
            call.args[0] == "git" and call.args[3:] == (
                "push", "origin", "HEAD:refs/heads/fix/update-ruling-for-feature",
            ) for call in run.call_args_list
        ))
        run.assert_any_call(
            "gh", "pr", "comment", "123", "--body",
            "⚖️ Ruling update ready for review: https://github.com/org/repo/pull/1",
        )
        self.assertFalse(any("stash" in call.args or "switch" in call.args for call in run.call_args_list))
        remote.assert_called_once()
        transfer.assert_called_once()
        staged.assert_called_once()

    @patch.object(create_fix_pr, "run")
    @patch.object(create_fix_pr, "has_staged_changes", return_value=False)
    @patch.object(create_fix_pr, "transfer_ruling_changes")
    @patch.object(create_fix_pr.subprocess, "run", return_value=SimpleNamespace(
        returncode=0, stdout=f"{'c' * 40}\trefs/heads/fix/update-ruling-for-feature\n",
    ))
    def test_existing_branch_reuses_its_pull_request(self, remote, transfer, staged, run) -> None:
        def command_output(*command: str, **kwargs) -> str:
            if command[:3] == ("gh", "pr", "list"):
                return "https://github.com/org/repo/pull/1"
            if "rev-parse" in command:
                return "b" * 40
            return ""

        with patch.object(create_fix_pr, "output", side_effect=command_output) as get_output:
            url, base_sha, sha = create_fix_pr.create_fix_pr("feature", "its/ruling", "")

        self.assertEqual(url, "https://github.com/org/repo/pull/1")
        self.assertEqual(base_sha, "b" * 40)
        self.assertEqual(sha, "b" * 40)
        self.assertFalse(any(call.args[:3] == ("gh", "pr", "create") for call in get_output.call_args_list))
        self.assertFalse(any("push" in call.args for call in run.call_args_list))
        remote.assert_called_once()
        transfer.assert_called_once()
        staged.assert_called_once()

    def test_dirty_checkout_does_not_block_clean_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            origin = root / "origin.git"
            source = root / "source"
            target = root / "target"
            ruling_root = Path("its/ruling/src/test/resources")
            project = ruling_root / "expected/project"

            def git(*arguments: str, cwd: Path) -> str:
                return subprocess.run(
                    ("git", *arguments), cwd=cwd, check=True, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True,
                ).stdout.strip()

            git("init", "--bare", str(origin), cwd=root)
            git("init", "-b", "feature", str(source), cwd=root)
            git("config", "user.name", "Test", cwd=source)
            git("config", "user.email", "test@example.com", cwd=source)
            (source / project).mkdir(parents=True)
            (source / "pom.xml").write_text("original")
            (source / project / "report.json").write_text("old")
            (source / project / "deleted.json").write_text("old")
            git("add", ".", cwd=source)
            git("commit", "-m", "Initial files", cwd=source)
            git("remote", "add", "origin", str(origin), cwd=source)
            git("push", "-u", "origin", "feature", cwd=source)

            git("clone", "--branch", "feature", str(origin), str(target), cwd=root)
            git("config", "user.name", "Test", cwd=target)
            git("config", "user.email", "test@example.com", cwd=target)
            (target / "pom.xml").write_text("target branch version")
            git("add", "pom.xml", cwd=target)
            git("commit", "-m", "Move target branch", cwd=target)
            git("push", "origin", "feature", cwd=target)

            (source / "pom.xml").write_text("dirty local version")
            (source / project / "report.json").write_text("new")
            (source / project / "deleted.json").unlink()
            (source / project / "added.json").write_text("added")

            original_output = create_fix_pr.output
            def fake_output(*command: str, **kwargs) -> str:
                if command[:3] in (("gh", "pr", "create"), ("gh", "pr", "list")):
                    return "https://example.test/fix"
                return original_output(*command, **kwargs)

            previous_directory = Path.cwd()
            try:
                os.chdir(source)
                with patch.object(create_fix_pr, "output", side_effect=fake_output):
                    url, base, head = create_fix_pr.create_fix_pr("feature", str(ruling_root), "")
                    self.assertEqual(url, "https://example.test/fix")
                    self.assertEqual(base, git("rev-parse", "HEAD", cwd=target))
                    self.assertEqual(head, git("--git-dir", str(origin), "rev-parse",
                        "refs/heads/fix/update-ruling-for-feature", cwd=root))
                    (source / project / "report.json").write_text("newer")
                    _, _, updated_head = create_fix_pr.create_fix_pr("feature", str(ruling_root), "")
                    self.assertNotEqual(updated_head, head)
                    (target / project / "report.json").write_text("conflicting target version")
                    git("add", str(project / "report.json"), cwd=target)
                    git("commit", "-m", "Change target ruling", cwd=target)
                    git("push", "origin", "feature", cwd=target)
                    with self.assertRaises(subprocess.CalledProcessError):
                        create_fix_pr.create_fix_pr("feature", str(ruling_root), "")
            finally:
                os.chdir(previous_directory)

            fix_ref = "refs/heads/fix/update-ruling-for-feature"
            self.assertEqual(git("--git-dir", str(origin), "show", f"{fix_ref}:pom.xml", cwd=root),
                "target branch version")
            self.assertEqual(git("--git-dir", str(origin), "show",
                f"{fix_ref}:{project}/report.json", cwd=root), "newer")
            self.assertEqual(git("--git-dir", str(origin), "show",
                f"{fix_ref}:{project}/added.json", cwd=root), "added")
            self.assertNotIn(str(project / "deleted.json"),
                git("--git-dir", str(origin), "ls-tree", "-r", "--name-only", fix_ref, cwd=root))
            self.assertEqual((source / "pom.xml").read_text(), "dirty local version")
            self.assertEqual((source / project / "added.json").read_text(), "added")
            self.assertEqual(git("worktree", "list", "--porcelain", cwd=source).count("worktree "), 1)


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
            with self.assertRaisesRegex(ValueError, "Both expected ruling directories exist") as ambiguous:
                find_ruling_directory.find_ruling_paths(root)
            self.assertIn(str(find_ruling_directory.PUBLIC_ROOT / "expected"), str(ambiguous.exception))
            self.assertIn(str(find_ruling_directory.PRIVATE_ROOT / "expected"), str(ambiguous.exception))

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


class CleanupFixPullRequestTests(unittest.TestCase):
    @patch.object(cleanup_fix_pr.subprocess, "run")
    def test_closes_open_pr_and_deletes_fix_branch(self, process) -> None:
        process.side_effect = [
            SimpleNamespace(returncode=0, stdout="OPEN\n"),
            SimpleNamespace(returncode=0),
            SimpleNamespace(returncode=1),
        ]
        self.assertTrue(cleanup_fix_pr.cleanup_fix_pr("feature"))
        branch = "fix/update-ruling-for-feature"
        self.assertEqual(process.call_args_list[0].args[0],
            ("gh", "pr", "view", branch, "--json", "state", "--jq", ".state"))
        self.assertEqual(process.call_args_list[1].args[0][:4], ("gh", "pr", "close", branch))
        self.assertEqual(process.call_args_list[2].args[0],
            ("git", "push", "origin", "--delete", branch))
        self.assertTrue(process.call_args_list[1].kwargs["check"])
        self.assertFalse(process.call_args_list[2].kwargs["check"])

    @patch.object(cleanup_fix_pr.subprocess, "run")
    def test_no_open_pr_does_not_delete_branch(self, process) -> None:
        for result in (SimpleNamespace(returncode=1, stdout=""),
                       SimpleNamespace(returncode=0, stdout="CLOSED\n")):
            process.reset_mock()
            process.return_value = result
            self.assertFalse(cleanup_fix_pr.cleanup_fix_pr("feature"))
            process.assert_called_once()

    @patch.object(cleanup_fix_pr.subprocess, "run")
    def test_close_failure_prevents_branch_deletion(self, process) -> None:
        process.side_effect = [
            SimpleNamespace(returncode=0, stdout="OPEN\n"),
            cleanup_fix_pr.subprocess.CalledProcessError(1, "gh pr close"),
        ]
        with self.assertRaises(cleanup_fix_pr.subprocess.CalledProcessError):
            cleanup_fix_pr.cleanup_fix_pr("feature")
        self.assertEqual(process.call_count, 2)


if __name__ == "__main__":
    unittest.main()
