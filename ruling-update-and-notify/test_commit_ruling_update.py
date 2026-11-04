from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import commit_ruling_update
from create_fix_pr import GENERATED_MARKER


class CommitRulingUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.origin = self.root / "origin.git"
        self.source = self.root / "source"
        self.peer = self.root / "peer"
        self.ruling_root = Path("its/ruling/src/test/resources")
        self.project = self.ruling_root / "expected/project"
        self.git("init", "--bare", str(self.origin), cwd=self.root)
        self.git("init", "-b", "feature", str(self.source), cwd=self.root)
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.test")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", "/dev/null")
        (self.source / self.project).mkdir(parents=True)
        (self.source / self.project / "report.json").write_text("old")
        (self.source / self.project / "deleted.json").write_text("deleted")
        (self.source / "unrelated.txt").write_text("original")
        self.git("add", ".")
        self.git("commit", "-m", "Initial files")
        self.head_sha = self.git("rev-parse", "HEAD")
        self.git("remote", "add", "origin", str(self.origin))
        self.git("push", "-u", "origin", "feature")
        self.git("clone", "--branch", "feature", str(self.origin), str(self.peer), cwd=self.root)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(self.source)

    def git(self, *arguments: str, cwd: Path | None = None) -> str:
        return subprocess.run(
            ("git", "-c", "user.name=Test", "-c", "user.email=test@example.test",
             "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *arguments),
            cwd=cwd or self.source, check=True, capture_output=True, text=True,
        ).stdout.strip()

    def update(self, head_sha: str | None = None) -> tuple[str, str]:
        return commit_ruling_update.commit_ruling_update(
            "feature", str(self.ruling_root), self.head_sha if head_sha is None else head_sha
        )

    def remote_head(self) -> str:
        return self.git("rev-parse", "refs/heads/feature", cwd=self.origin)

    def advance_peer(self) -> str:
        (self.peer / "another.txt").write_text("new work")
        self.git("add", ".", cwd=self.peer)
        self.git("commit", "-m", "Advance branch", cwd=self.peer)
        self.git("push", "origin", "feature", cwd=self.peer)
        return self.git("rev-parse", "HEAD", cwd=self.peer)

    def test_pushes_only_ruling_changes_and_preserves_dirty_checkout(self) -> None:
        (self.source / self.project / "report.json").write_text("new")
        (self.source / self.project / "deleted.json").unlink()
        (self.source / self.project / "added.json").write_text("added")
        (self.source / "unrelated.txt").write_text("staged unrelated edit")
        self.git("add", "unrelated.txt")
        (self.source / "untracked.txt").write_text("untracked unrelated edit")
        original_status = self.git("status", "--porcelain")
        with patch.object(commit_ruling_update, "run", wraps=commit_ruling_update.run) as run:
            base_sha, update_sha = self.update()

        self.assertEqual(base_sha, self.head_sha)
        self.assertNotEqual(update_sha, base_sha)
        self.assertEqual(self.remote_head(), update_sha)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.head_sha)
        self.assertEqual(self.git("status", "--porcelain"), original_status)
        self.assertEqual(self.git("show", f"{update_sha}^", "--format=%H", "--no-patch"), base_sha)
        self.assertEqual(
            set(self.git("diff", "--name-only", base_sha, update_sha).splitlines()),
            {str(self.project / name) for name in ("report.json", "deleted.json", "added.json")},
        )
        self.assertEqual(self.git("show", f"{update_sha}:unrelated.txt"), "original")
        self.assertEqual(self.git("show", f"{update_sha}:{self.project}/report.json"), "new")
        self.assertEqual(self.git("show", f"{update_sha}:{self.project}/added.json"), "added")
        self.assertNotIn(str(self.project / "deleted.json"), self.git("ls-tree", "-r", "--name-only", update_sha))
        self.assertIn(GENERATED_MARKER, self.git("show", "-s", "--format=%B", update_sha))
        self.assertEqual(self.git("show", "-s", "--format=%an", update_sha), "github-actions[bot]")
        self.assertEqual(self.git("branch", "--list", "fix/*"), "")
        self.assertEqual(self.git("worktree", "list", "--porcelain").count("worktree "), 1)
        commands = [call.args for call in run.call_args_list]
        pushes = [command for command in commands if "push" in command]
        self.assertEqual(len(pushes), 1)
        self.assertEqual(pushes[0][-3:], ("push", "origin", "HEAD:refs/heads/feature"))
        self.assertFalse(any(command[0] == "gh" for command in commands))

    def test_no_changes_does_not_commit_or_push(self) -> None:
        with patch.object(commit_ruling_update, "run", wraps=commit_ruling_update.run) as run:
            self.assertEqual(self.update(), (self.head_sha, ""))
        self.assertEqual(self.remote_head(), self.head_sha)
        self.assertFalse(any("push" in call.args or "commit" in call.args for call in run.call_args_list))
        self.assertEqual(self.git("worktree", "list", "--porcelain").count("worktree "), 1)

    def test_rejects_stale_remote_branch(self) -> None:
        new_head = self.advance_peer()
        (self.source / self.project / "report.json").write_text("new")
        with self.assertRaisesRegex(RuntimeError, "refusing a stale ruling update"):
            self.update()
        self.assertEqual(self.remote_head(), new_head)
        self.assertEqual((self.source / self.project / "report.json").read_text(), "new")

    def test_rejects_checkout_that_is_not_the_pr_head(self) -> None:
        new_head = self.advance_peer()
        with self.assertRaisesRegex(RuntimeError, "checkout must match the PR head SHA"):
            self.update(new_head)
        self.assertEqual(self.remote_head(), new_head)

    def test_requires_pr_head_sha(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "PR head SHA is required"):
            self.update("")

    def test_rejects_a_concurrent_push_without_overwriting_it(self) -> None:
        (self.source / self.project / "report.json").write_text("new")
        original_run = commit_ruling_update.run
        remote_sha = self.head_sha

        def run_with_racing_push(*command: str) -> None:
            nonlocal remote_sha
            if "push" in command:
                remote_sha = self.advance_peer()
            original_run(*command)

        with patch.object(commit_ruling_update, "run", side_effect=run_with_racing_push):
            with self.assertRaises(subprocess.CalledProcessError):
                self.update()
        self.assertNotEqual(remote_sha, self.head_sha)
        self.assertEqual(self.remote_head(), remote_sha)
        self.assertEqual(self.git("show", f"{remote_sha}:{self.project}/report.json", cwd=self.origin), "old")
        self.assertEqual(self.git("worktree", "list", "--porcelain").count("worktree "), 1)

    def test_cleans_up_worktree_when_transfer_fails(self) -> None:
        with patch.object(commit_ruling_update, "transfer_ruling_changes", side_effect=RuntimeError("conflict")):
            with self.assertRaisesRegex(RuntimeError, "conflict"):
                self.update()
        self.assertEqual(self.remote_head(), self.head_sha)
        self.assertEqual(self.git("worktree", "list", "--porcelain").count("worktree "), 1)


class CommitRulingUpdateMainTests(unittest.TestCase):
    def test_main_publishes_base_and_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            with (
                patch.dict(os.environ, {
                    "TARGET_REF": "feature", "RULING_ROOT": "its/ruling",
                    "PR_HEAD_SHA": "a" * 40, "GITHUB_OUTPUT": str(output),
                }),
                patch.object(commit_ruling_update, "commit_ruling_update", return_value=("a" * 40, "b" * 40)) as commit,
            ):
                self.assertEqual(commit_ruling_update.main(), 0)
            commit.assert_called_once_with("feature", "its/ruling", "a" * 40)
            self.assertEqual(output.read_text(), f"update-base-sha={'a' * 40}\nupdate-sha={'b' * 40}\n")

    def test_failure_reports_error_without_publishing_outputs(self) -> None:
        for failure in (RuntimeError("stale head"), subprocess.CalledProcessError(1, "git push")):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "outputs"
                errors = StringIO()
                with (
                    patch.dict(os.environ, {
                        "TARGET_REF": "feature", "RULING_ROOT": "its/ruling",
                        "PR_HEAD_SHA": "a" * 40, "GITHUB_OUTPUT": str(output),
                    }),
                    patch.object(commit_ruling_update, "commit_ruling_update", side_effect=failure),
                    redirect_stderr(errors),
                ):
                    self.assertEqual(commit_ruling_update.main(), 1)
                self.assertFalse(output.exists())
                self.assertIn("::error::", errors.getvalue())


class UpdateModeValidationTests(unittest.TestCase):
    def run_setup(self, **overrides: str) -> subprocess.CompletedProcess:
        action = Path(__file__).with_name("action.yml").read_text()
        step = action.split("    - name: Setup environment variables\n", 1)[1].split("\n    - name:", 1)[0]
        script = "\n".join(line[8:] for line in step.split("      run: |\n", 1)[1].splitlines())
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                **os.environ, "UPDATE_MODE": "pull-request", "RULING_FAILED": "true",
                "GITHUB_PR_NUMBER": "123", "GITHUB_HEAD_REF": "feature", "GITHUB_REF_NAME": "123/merge",
                "PR_HEAD_REPOSITORY": "owner/repo", "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_OUTPUT": str(Path(directory) / "outputs"), **overrides,
            }
            return subprocess.run(
                ("bash", "-e", "-c", script), env=environment, capture_output=True, text=True,
            )

    def test_accepts_both_modes_for_same_repository_prs(self) -> None:
        for mode in ("pull-request", "commit"):
            with self.subTest(mode=mode):
                result = self.run_setup(UPDATE_MODE=mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rejects_unknown_mode(self) -> None:
        result = self.run_setup(UPDATE_MODE="typo")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("update-mode must be pull-request or commit", result.stdout)

    def test_commit_mode_rejects_forks(self) -> None:
        result = self.run_setup(UPDATE_MODE="commit", PR_HEAD_REPOSITORY="contributor/fork")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("only supports same-repository pull requests", result.stdout)

    def test_commit_mode_requires_a_pr(self) -> None:
        result = self.run_setup(UPDATE_MODE="commit", GITHUB_PR_NUMBER="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires a pull request event", result.stdout)

    def test_default_mode_still_accepts_pushes(self) -> None:
        result = self.run_setup(GITHUB_PR_NUMBER="", GITHUB_HEAD_REF="", GITHUB_REF_NAME="master")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
